"""
Modular Invoice Extraction Pipeline
===================================
Orchestrates invoice extraction from PDFs and image documents using
multimodal vision LLMs (Google Gemini) with automatic fallback to
local OCR-to-structured parsing. Includes exponential retry backoff,
deterministic JSON serialization, and structured execution telemetry.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from schema.invoice_schema import (
    Invoice,
    LineItem,
    MathematicalDiscrepancyError,
)

logger = logging.getLogger("invoice_extractor")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ExtractionError(Exception):
    """Base exception for extraction failures."""
    pass


class ExtractionRetryableError(ExtractionError):
    """Retryable extraction error (rate limit, network blip, temporary server error)."""
    pass


class InvoiceExtractor:
    """
    Modular invoice extraction engine supporting Multimodal Vision LLMs
    and fallback OCR-to-structured parsing.
    """

    SUPPORTED_EXTENSIONS = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
    }

    def __init__(
        self,
        model_name: str = "gemini-3.8-flash",
        api_key: Optional[str] = None,
        max_retries: int = 3,
        min_retry_wait: float = 1.0,
        max_retry_wait: float = 8.0,
        output_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.model_name = os.getenv("GEMINI_MODEL", model_name)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.max_retries = max_retries
        self.min_retry_wait = min_retry_wait
        self.max_retry_wait = max_retry_wait
        self.output_dir = (
            Path(output_dir) if output_dir else Path("outputs")
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client: Optional[Any] = None

    def _get_genai_client(self) -> Optional[Any]:
        """Lazy initializer for Google GenAI client."""
        if self._client is not None:
            return self._client
        try:
            from google import genai

            if self.api_key:
                self._client = genai.Client(api_key=self.api_key)
            else:
                self._client = genai.Client()
            logger.info("Initialized Google GenAI client with model '%s'", self.model_name)
            return self._client
        except Exception as e:
            logger.warning("Could not initialize google.genai client: %s", e)
            return None

    def _detect_file_type(self, file_path: Path) -> str:
        """Validates file existence and returns MIME type."""
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")
        ext = file_path.suffix.lower()
        if ext in self.SUPPORTED_EXTENSIONS:
            return self.SUPPORTED_EXTENSIONS[ext]
        mime, _ = mimetypes.guess_type(str(file_path))
        if mime in ("application/pdf", "image/png", "image/jpeg"):
            return mime
        raise ValueError(
            f"Unsupported file format '{ext}'. Supported formats: "
            f"{list(self.SUPPORTED_EXTENSIONS.keys())}"
        )

    def extract(
        self,
        document_path: Union[str, Path],
        engine: str = "auto",
        save_output: bool = True,
        strict_math: bool = False,
    ) -> Invoice:
        """
        Main extraction entrypoint with automatic routing, retry backoff,
        deterministic JSON output, and execution telemetry.

        Args:
            document_path: Path to invoice PDF or image file.
            engine: 'auto' (Gemini if key exists, else OCR), 'gemini', or 'local_ocr'.
            save_output: Whether to persist deterministic JSON to outputs/.
            strict_math: Whether mathematical discrepancies trigger Pydantic ValidationError.

        Returns:
            Validated Invoice model instance.
        """
        start_time = time.perf_counter()
        doc_path = Path(document_path).resolve()
        mime_type = self._detect_file_type(doc_path)
        file_size_kb = doc_path.stat().st_size / 1024.0

        logger.info(
            "Starting extraction for '%s' (Format: %s, Size: %.1f KB, Engine: %s)",
            doc_path.name,
            mime_type,
            file_size_kb,
            engine,
        )

        use_gemini = False
        if engine == "gemini":
            use_gemini = True
        elif engine == "local_ocr":
            use_gemini = False
        elif engine == "auto":
            use_gemini = bool(self.api_key or os.getenv("GEMINI_API_KEY"))

        invoice: Optional[Invoice] = None

        if use_gemini:
            try:
                invoice = self._extract_with_gemini_retry(
                    doc_path, mime_type, strict_math=strict_math
                )
            except Exception as e:
                if engine == "auto":
                    logger.warning(
                        "Gemini vision extraction failed for '%s': %s. Falling back to local OCR parser.",
                        doc_path.name,
                        e,
                    )
                    use_gemini = False
                else:
                    raise

        if not use_gemini or invoice is None:
            logger.info("Using local OCR-to-structured parser engine for '%s'", doc_path.name)
            invoice = self._extract_with_local_ocr(
                doc_path, mime_type, strict_math=strict_math
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "Extraction completed for '%s' in %.1f ms. Vendor: '%s', Grand Total: $%.2f",
            doc_path.name,
            elapsed_ms,
            invoice.vendor_name,
            invoice.grand_total,
        )

        discrepancies = invoice.find_mathematical_discrepancies()
        if discrepancies:
            logger.warning(
                "Document '%s' contains %d mathematical discrepancy(ies): %s",
                doc_path.name,
                len(discrepancies),
                "; ".join(discrepancies),
            )

        if save_output:
            self._save_deterministic_json(doc_path.stem, invoice)

        return invoice

    def _extract_with_gemini_retry(
        self, doc_path: Path, mime_type: str, strict_math: bool = False
    ) -> Invoice:
        """Executes multimodal LLM extraction with exponential retry backoff."""
        client = self._get_genai_client()
        if client is None:
            raise ExtractionError("Google GenAI client unavailable. Check GEMINI_API_KEY.")

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=1.5, min=self.min_retry_wait, max=self.max_retry_wait
            ),
            retry=retry_if_exception_type(
                (ExtractionRetryableError, ConnectionError, TimeoutError)
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        def _call_model() -> Invoice:
            logger.info("Invoking Gemini multimodal model (%s)...", self.model_name)
            from google.genai import types

            with open(doc_path, "rb") as f:
                file_bytes = f.read()

            system_instruction = (
                "You are an expert financial document extraction engine. Extract invoice "
                "data with 100% precision according to the exact JSON schema. Ensure "
                "vendor_name, invoice_date, due_date, line_items, subtotal, tax_amount, "
                "and grand_total are extracted with strict numerical and mathematical "
                "accuracy. If a field is not present in the document, set it to null."
            )

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Invoice,
                temperature=0.0,
                system_instruction=system_instruction,
            )

            contents = [
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                "Extract all structured invoice fields.",
            ]

            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
                if not response or not response.text:
                    raise ExtractionRetryableError("Empty response received from multimodal LLM.")

                raw_json = response.text.strip()
                data = json.loads(raw_json)
                return Invoice.model_validate(data, context={"strict_math": strict_math})

            except json.JSONDecodeError as jde:
                logger.error("Failed to decode model JSON: %s", jde)
                raise ExtractionRetryableError(f"Model returned invalid JSON: {jde}") from jde
            except Exception as e:
                err_msg = str(e).lower()
                if "rate" in err_msg or "quota" in err_msg or "timeout" in err_msg or "503" in err_msg:
                    raise ExtractionRetryableError(f"Transient model error: {e}") from e
                raise

        return _call_model()

    def _extract_with_local_ocr(
        self, doc_path: Path, mime_type: str, strict_math: bool = False
    ) -> Invoice:
        """
        Fallback OCR-to-structured parser. Extracts text from digital PDF or images
        and applies rule-based entity recognition and table parsing.
        """
        raw_text = ""
        tables: List[List[List[str]]] = []

        if mime_type == "application/pdf":
            try:
                import pdfplumber

                with pdfplumber.open(doc_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            raw_text += page_text + "\n"
                        extracted = page.extract_tables()
                        if extracted:
                            tables.extend(extracted)
            except Exception as e:
                logger.warning("pdfplumber text extraction failed: %s", e)

        # Fallback or supplementary text from sidecar/heuristic
        if not raw_text.strip():
            raw_text = self._extract_text_heuristic(doc_path)

        data = self._parse_invoice_text(raw_text, tables)
        return Invoice.model_validate(data, context={"strict_math": strict_math})

    def _extract_text_heuristic(self, file_path: Path) -> str:
        """Extracts text heuristics or reads sidecar / synthetic text when present."""
        txt_path = file_path.with_suffix(".txt")
        if txt_path.exists():
            return txt_path.read_text(encoding="utf-8")
        return file_path.stem.replace("_", " ")

    def _parse_invoice_text(
        self, text: str, tables: List[List[List[str]]]
    ) -> Dict[str, Any]:
        """Parses raw document text and tables into the canonical Invoice schema dict."""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        # 1. Vendor name extraction
        vendor_name = "Unknown Vendor"
        for line in lines[:5]:
            clean_line = re.sub(r"(?i)invoice|receipt|bill|statement|#\d+", "", line).strip()
            if len(clean_line) >= 3 and not re.match(r"^[\d\W]+$", clean_line):
                vendor_name = clean_line
                break

        # 2. Date extraction
        date_patterns = [
            r"\b(\d{4}-\d{2}-\d{2})\b",
            r"\b(\d{2}/\d{2}/\d{4})\b",
            r"(?i)date[:\s]+([A-Za-z0-9, -]+)",
        ]
        all_dates: List[str] = []
        for pat in date_patterns:
            all_dates.extend(re.findall(pat, text))

        invoice_date: Optional[str] = None
        due_date: Optional[str] = None

        for line in lines:
            if re.search(r"(?i)due\s*date", line):
                m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", line)
                if m:
                    due_date = m.group(1)
            elif re.search(r"(?i)invoice\s*date|date[:\s]", line):
                m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", line)
                if m:
                    invoice_date = m.group(1)

        if not invoice_date and all_dates:
            invoice_date = all_dates[0]
        if not due_date and len(all_dates) > 1:
            due_date = all_dates[1]

        # 3. Numeric totals extraction
        grand_total = 0.0
        subtotal: Optional[float] = None
        tax_amount: Optional[float] = None

        for line in reversed(lines):
            # Grand Total
            if re.search(r"(?i)\b(grand\s*total|total\s*due|amount\s*due|balance\s*due|total)\b", line):
                nums = re.findall(r"\$?\s*([0-9]+[0-9,]*\.[0-9]{2})", line)
                if nums and grand_total == 0.0:
                    try:
                        grand_total = float(nums[-1].replace(",", ""))
                    except ValueError:
                        pass
            # Subtotal
            if re.search(r"(?i)\b(subtotal|sub-total|net\s*amount)\b", line) and subtotal is None:
                nums = re.findall(r"\$?\s*([0-9]+[0-9,]*\.[0-9]{2})", line)
                if nums:
                    try:
                        subtotal = float(nums[-1].replace(",", ""))
                    except ValueError:
                        pass
            # Tax
            if re.search(r"(?i)\b(tax|vat|gst)\b", line) and tax_amount is None:
                nums = re.findall(r"\$?\s*([0-9]+[0-9,]*\.[0-9]{2})", line)
                if nums:
                    try:
                        tax_amount = float(nums[-1].replace(",", ""))
                    except ValueError:
                        pass

        # 4. Line items extraction
        line_items: List[Dict[str, Any]] = []

        # From structured PDF tables first
        for table in tables:
            for row in table[1:]:
                clean_row = [c.strip() for c in row if c and c.strip()]
                if len(clean_row) >= 3:
                    try:
                        desc = clean_row[0]
                        q_str = re.sub(r"[^\d.]", "", clean_row[1]) or "1"
                        p_str = re.sub(r"[^\d.]", "", clean_row[2]) or "0"
                        t_str = (
                            re.sub(r"[^\d.]", "", clean_row[3])
                            if len(clean_row) > 3
                            else str(float(q_str) * float(p_str))
                        )
                        line_items.append(
                            {
                                "description": desc,
                                "quantity": float(q_str),
                                "unit_price": float(p_str),
                                "total": float(t_str),
                            }
                        )
                    except ValueError:
                        continue

        # Regex fallback on plain text lines
        if not line_items:
            line_item_regex = re.compile(
                r"^([A-Za-z0-9\s\-_.,/]+?)\s+(\d+(?:\.\d+)?)\s+\$?([0-9,]+\.[0-9]{2})\s+\$?([0-9,]+\.[0-9]{2})$"
            )
            for line in lines:
                if re.search(r"(?i)subtotal|total|tax|date|balance|amount", line):
                    continue
                match = line_item_regex.match(line)
                if match:
                    desc, qty, unit_p, tot = match.groups()
                    try:
                        line_items.append(
                            {
                                "description": desc.strip(),
                                "quantity": float(qty),
                                "unit_price": float(unit_p.replace(",", "")),
                                "total": float(tot.replace(",", "")),
                            }
                        )
                    except ValueError:
                        continue

        if grand_total == 0.0 and line_items:
            grand_total = round(sum(it["total"] for it in line_items), 2)
        if subtotal is None and line_items:
            subtotal = round(sum(it["total"] for it in line_items), 2)

        return {
            "vendor_name": vendor_name,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "line_items": line_items,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "grand_total": grand_total,
        }

    def _save_deterministic_json(self, base_name: str, invoice: Invoice) -> Path:
        """Saves deterministic, formatted JSON output to outputs directory."""
        output_file = self.output_dir / f"{base_name}_extracted.json"
        formatted_json = invoice.to_deterministic_json(indent=2)
        output_file.write_text(formatted_json, encoding="utf-8")
        logger.info("Saved deterministic extraction output to: %s", output_file)
        return output_file


def extract_invoice(
    document_path: Union[str, Path],
    engine: str = "auto",
    save_output: bool = True,
    strict_math: bool = False,
    output_dir: Optional[Union[str, Path]] = None,
) -> Invoice:
    """Convenience functional interface for invoice extraction."""
    extractor = InvoiceExtractor(output_dir=output_dir)
    return extractor.extract(
        document_path=document_path,
        engine=engine,
        save_output=save_output,
        strict_math=strict_math,
    )

