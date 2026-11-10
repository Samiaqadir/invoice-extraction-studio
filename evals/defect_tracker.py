"""
Defect Tracker & Evaluation Module
==================================
Provides standardized defect taxonomy, logging, and evaluation metrics
for invoice extraction pipelines. Errors are systematically categorized into:
  1. field_missing: Required or expected fields missing/null.
  2. ocr_misrecognition: Character confusion, typographical or noisy text errors.
  3. decimal_misalignment: Power-of-10 shifted numeric values (e.g. 10x, 100x).
  4. mathematical_discrepancy: Line item products or subtotal/tax summation errors.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import difflib
from enum import Enum
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field

from schema.invoice_schema import Invoice, LineItem

logger = logging.getLogger("evals.defect_tracker")


class DefectType(str, Enum):
    """Canonical classification for invoice extraction defects."""
    FIELD_MISSING = "field_missing"
    OCR_MISRECOGNITION = "ocr_misrecognition"
    DECIMAL_MISALIGNMENT = "decimal_misalignment"
    MATHEMATICAL_DISCREPANCY = "mathematical_discrepancy"


class DefectSeverity(str, Enum):
    """Severity classification of identified defects."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DefectRecord(BaseModel):
    """Structured record of a single extraction defect."""
    model_config = ConfigDict(extra="forbid")

    defect_id: str = Field(
        default_factory=lambda: f"DEF-{uuid.uuid4().hex[:8].upper()}",
        description="Unique identifier for the defect instance.",
    )
    document_id: str = Field(..., description="Document identifier or filename.")
    defect_type: DefectType = Field(..., description="Canonical defect type.")
    field_path: str = Field(
        ...,
        description="Dot/bracket path to field (e.g., line_items[0].unit_price).",
    )
    expected_value: Any = Field(..., description="Ground truth benchmark value.")
    actual_value: Any = Field(..., description="Extracted predicted value.")
    severity: DefectSeverity = Field(..., description="Defect severity.")
    message: str = Field(..., description="Detailed diagnostic description.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp when defect was recorded.",
    )


class EvaluationSummary(BaseModel):
    """Aggregate statistics for an evaluation batch."""
    total_documents: int
    perfect_documents: int
    defective_documents: int
    total_defects: int
    defects_by_type: Dict[str, int]
    defects_by_severity: Dict[str, int]
    document_accuracy_rate: float
    field_accuracy_rate: float
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DefectTracker:
    """
    Evaluation manager tracking, categorizing, and reporting extraction defects.
    """

    def __init__(self, name: str = "InvoiceDefectTracker") -> None:
        self.name = name
        self.defects: List[DefectRecord] = []
        self._document_results: Dict[str, List[DefectRecord]] = {}

    def clear(self) -> None:
        """Resets the defect tracking state."""
        self.defects = []
        self._document_results = {}

    @staticmethod
    def _is_empty(val: Any) -> bool:
        """Checks if a value is considered missing or empty."""
        if val is None:
            return True
        if isinstance(val, str) and not val.strip():
            return True
        if isinstance(val, (list, dict)) and len(val) == 0:
            return True
        return False

    @staticmethod
    def _is_decimal_shift(expected: float, actual: float) -> Tuple[bool, Optional[str]]:
        """
        Determines if numeric divergence is due to power-of-10 decimal point misalignment.
        Examples: 12.50 vs 1250.0 (100x), 450.0 vs 45.0 (0.1x), 1.09 vs 109.0.
        """
        if expected <= 0 or actual <= 0 or expected == actual:
            return False, None

        ratio = actual / expected
        if ratio > 0:
            log10_ratio = math.log10(ratio)
            nearest_int = round(log10_ratio)
            if abs(log10_ratio - nearest_int) < 0.01 and abs(nearest_int) >= 1:
                factor = 10**nearest_int
                return (
                    True,
                    f"Shifted by factor of {factor}x ({expected} vs {actual})",
                )

        # Alternative: match digits ignoring decimal point
        exp_digits = f"{expected:.4f}".replace(".", "").strip("0")
        act_digits = f"{actual:.4f}".replace(".", "").strip("0")
        if exp_digits and act_digits and exp_digits == act_digits:
            return (
                True,
                f"Digit string matched ({exp_digits}) but decimal point misaligned: {expected} vs {actual}",
            )

        return False, None

    @staticmethod
    def _calculate_text_similarity(s1: str, s2: str) -> float:
        """Returns sequence matcher similarity ratio between 0.0 and 1.0."""
        return difflib.SequenceMatcher(
            None, s1.strip().lower(), s2.strip().lower()
        ).ratio()

    def evaluate_document(
        self,
        document_id: str,
        predicted: Union[Invoice, Dict[str, Any], None],
        ground_truth: Union[Invoice, Dict[str, Any]],
    ) -> List[DefectRecord]:
        """
        Compares predicted extraction against ground truth, records all detected defects,
        and categorizes them into field_missing, ocr_misrecognition, decimal_misalignment,
        or mathematical_discrepancy.
        """
        defects: List[DefectRecord] = []

        pred_dict: Optional[Dict[str, Any]] = None
        if isinstance(predicted, Invoice):
            pred_dict = predicted.model_dump()
        elif isinstance(predicted, dict):
            pred_dict = predicted

        gt_dict: Dict[str, Any] = (
            ground_truth.model_dump()
            if isinstance(ground_truth, Invoice)
            else dict(ground_truth)
        )

        # Case 1: Complete extraction failure
        if pred_dict is None:
            defects.append(
                DefectRecord(
                    document_id=document_id,
                    defect_type=DefectType.FIELD_MISSING,
                    field_path="root",
                    expected_value="Valid Invoice Data",
                    actual_value=None,
                    severity=DefectSeverity.CRITICAL,
                    message="Complete document extraction failed or returned null.",
                )
            )
            self._record_defects(document_id, defects)
            return defects

        # Case 2: Standard header field evaluation
        fields_to_check = (
            "vendor_name",
            "invoice_date",
            "due_date",
            "subtotal",
            "tax_amount",
            "grand_total",
        )
        required_fields = ("vendor_name", "grand_total")

        for field in fields_to_check:
            expected_val = gt_dict.get(field)
            actual_val = pred_dict.get(field)

            # Check for missing field
            if not self._is_empty(expected_val) and self._is_empty(actual_val):
                severity = (
                    DefectSeverity.HIGH
                    if field in required_fields
                    else DefectSeverity.MEDIUM
                )
                defects.append(
                    DefectRecord(
                        document_id=document_id,
                        defect_type=DefectType.FIELD_MISSING,
                        field_path=field,
                        expected_value=expected_val,
                        actual_value=actual_val,
                        severity=severity,
                        message=f"Required/expected field '{field}' is missing or empty in extraction.",
                    )
                )
            elif expected_val is not None and actual_val is not None:
                # Numeric field comparison
                if isinstance(expected_val, (int, float)) and isinstance(
                    actual_val, (int, float)
                ):
                    diff = abs(float(expected_val) - float(actual_val))
                    if diff > 0.02:
                        is_shift, shift_desc = self._is_decimal_shift(
                            float(expected_val), float(actual_val)
                        )
                        if is_shift:
                            defects.append(
                                DefectRecord(
                                    document_id=document_id,
                                    defect_type=DefectType.DECIMAL_MISALIGNMENT,
                                    field_path=field,
                                    expected_value=expected_val,
                                    actual_value=actual_val,
                                    severity=DefectSeverity.HIGH,
                                    message=f"Decimal misalignment on '{field}': {shift_desc}",
                                )
                            )
                        else:
                            defects.append(
                                DefectRecord(
                                    document_id=document_id,
                                    defect_type=DefectType.OCR_MISRECOGNITION,
                                    field_path=field,
                                    expected_value=expected_val,
                                    actual_value=actual_val,
                                    severity=DefectSeverity.MEDIUM,
                                    message=(
                                        f"Numeric OCR misrecognition on '{field}': "
                                        f"expected {expected_val}, got {actual_val}"
                                    ),
                                )
                            )

                # Text field comparison
                elif isinstance(expected_val, str) and isinstance(actual_val, str):
                    if expected_val.strip() != actual_val.strip():
                        sim = self._calculate_text_similarity(
                            expected_val, actual_val
                        )
                        defects.append(
                            DefectRecord(
                                document_id=document_id,
                                defect_type=DefectType.OCR_MISRECOGNITION,
                                field_path=field,
                                expected_value=expected_val,
                                actual_value=actual_val,
                                severity=(
                                    DefectSeverity.MEDIUM
                                    if sim >= 0.8
                                    else DefectSeverity.HIGH
                                ),
                                message=(
                                    f"Text OCR misrecognition on '{field}' (similarity: {sim:.2%}): "
                                    f"expected '{expected_val}', got '{actual_val}'"
                                ),
                            )
                        )

        # Case 3: Line items comparison
        gt_items = gt_dict.get("line_items", []) or []
        pred_items = pred_dict.get("line_items", []) or []

        if len(gt_items) > 0 and len(pred_items) == 0:
            defects.append(
                DefectRecord(
                    document_id=document_id,
                    defect_type=DefectType.FIELD_MISSING,
                    field_path="line_items",
                    expected_value=f"{len(gt_items)} items",
                    actual_value="0 items",
                    severity=DefectSeverity.HIGH,
                    message=(
                        f"Extracted zero line items; ground truth contains {len(gt_items)} line items."
                    ),
                )
            )
        else:
            for idx, exp_item in enumerate(gt_items):
                if idx >= len(pred_items):
                    defects.append(
                        DefectRecord(
                            document_id=document_id,
                            defect_type=DefectType.FIELD_MISSING,
                            field_path=f"line_items[{idx}]",
                            expected_value=exp_item,
                            actual_value=None,
                            severity=DefectSeverity.HIGH,
                            message=(
                                f"Missing line item #{idx + 1}: '{exp_item.get('description', '')}'"
                            ),
                        )
                    )
                else:
                    act_item = pred_items[idx]
                    # Description check
                    exp_desc = str(exp_item.get("description", "")).strip()
                    act_desc = str(act_item.get("description", "")).strip()
                    if exp_desc != act_desc:
                        sim = self._calculate_text_similarity(exp_desc, act_desc)
                        defects.append(
                            DefectRecord(
                                document_id=document_id,
                                defect_type=DefectType.OCR_MISRECOGNITION,
                                field_path=f"line_items[{idx}].description",
                                expected_value=exp_desc,
                                actual_value=act_desc,
                                severity=(
                                    DefectSeverity.LOW
                                    if sim >= 0.8
                                    else DefectSeverity.MEDIUM
                                ),
                                message=(
                                    f"Line item #{idx + 1} description OCR noise ({sim:.2%}): "
                                    f"'{act_desc}' != '{exp_desc}'"
                                ),
                            )
                        )

                    # Numeric line item fields
                    for num_f in ("quantity", "unit_price", "total"):
                        exp_n = exp_item.get(num_f)
                        act_n = act_item.get(num_f)
                        if exp_n is not None and act_n is None:
                            defects.append(
                                DefectRecord(
                                    document_id=document_id,
                                    defect_type=DefectType.FIELD_MISSING,
                                    field_path=f"line_items[{idx}].{num_f}",
                                    expected_value=exp_n,
                                    actual_value=act_n,
                                    severity=DefectSeverity.MEDIUM,
                                    message=f"Line item #{idx + 1} missing {num_f}",
                                )
                            )
                        elif exp_n is not None and act_n is not None:
                            diff = abs(float(exp_n) - float(act_n))
                            if diff > 0.02:
                                is_shift, shift_desc = self._is_decimal_shift(
                                    float(exp_n), float(act_n)
                                )
                                if is_shift:
                                    defects.append(
                                        DefectRecord(
                                            document_id=document_id,
                                            defect_type=DefectType.DECIMAL_MISALIGNMENT,
                                            field_path=f"line_items[{idx}].{num_f}",
                                            expected_value=exp_n,
                                            actual_value=act_n,
                                            severity=DefectSeverity.HIGH,
                                            message=(
                                                f"Line item #{idx + 1} {num_f} decimal shifted: {shift_desc}"
                                            ),
                                        )
                                    )
                                else:
                                    defects.append(
                                        DefectRecord(
                                            document_id=document_id,
                                            defect_type=DefectType.OCR_MISRECOGNITION,
                                            field_path=f"line_items[{idx}].{num_f}",
                                            expected_value=exp_n,
                                            actual_value=act_n,
                                            severity=DefectSeverity.MEDIUM,
                                            message=(
                                                f"Line item #{idx + 1} {num_f} mismatch: "
                                                f"expected {exp_n}, got {act_n}"
                                            ),
                                        )
                                    )

        # Case 4: Internal mathematical consistency of prediction
        math_defects = self._check_prediction_math_discrepancies(
            document_id, pred_dict
        )
        defects.extend(math_defects)

        self._record_defects(document_id, defects)
        return defects

    def _check_prediction_math_discrepancies(
        self, document_id: str, pred_dict: Dict[str, Any]
    ) -> List[DefectRecord]:
        """Validates internal arithmetic consistency of the extracted prediction."""
        math_defects: List[DefectRecord] = []

        subtotal = pred_dict.get("subtotal")
        tax = pred_dict.get("tax_amount")
        grand_total = pred_dict.get("grand_total")
        line_items = pred_dict.get("line_items", []) or []

        # 1. Header equation: subtotal + tax == grand_total
        if subtotal is not None and tax is not None and grand_total is not None:
            expected_grand = round(float(subtotal) + float(tax), 2)
            actual_grand = round(float(grand_total), 2)
            diff = abs(expected_grand - actual_grand)
            if diff > 0.02:
                math_defects.append(
                    DefectRecord(
                        document_id=document_id,
                        defect_type=DefectType.MATHEMATICAL_DISCREPANCY,
                        field_path="grand_total",
                        expected_value=expected_grand,
                        actual_value=actual_grand,
                        severity=DefectSeverity.HIGH,
                        message=(
                            f"Header arithmetic mismatch: subtotal ({subtotal}) + tax ({tax}) = "
                            f"{expected_grand} != grand_total ({actual_grand}) [diff: {diff:.2f}]"
                        ),
                    )
                )

        # 2. Line item summation vs subtotal
        if line_items and subtotal is not None:
            items_sum = round(
                sum(float(it.get("total", 0.0)) for it in line_items), 2
            )
            actual_subtotal = round(float(subtotal), 2)
            diff = abs(items_sum - actual_subtotal)
            if diff > 0.02:
                math_defects.append(
                    DefectRecord(
                        document_id=document_id,
                        defect_type=DefectType.MATHEMATICAL_DISCREPANCY,
                        field_path="subtotal",
                        expected_value=items_sum,
                        actual_value=actual_subtotal,
                        severity=DefectSeverity.HIGH,
                        message=(
                            f"Line items total sum ({items_sum}) does not equal "
                            f"subtotal ({actual_subtotal}) [diff: {diff:.2f}]"
                        ),
                    )
                )

        # 3. Line item multiplication: quantity * unit_price == total
        for i, it in enumerate(line_items):
            q = it.get("quantity")
            p = it.get("unit_price")
            t = it.get("total")
            if q is not None and p is not None and t is not None:
                expected_tot = round(float(q) * float(p), 2)
                actual_tot = round(float(t), 2)
                diff = abs(expected_tot - actual_tot)
                if diff > 0.02:
                    math_defects.append(
                        DefectRecord(
                            document_id=document_id,
                            defect_type=DefectType.MATHEMATICAL_DISCREPANCY,
                            field_path=f"line_items[{i}].total",
                            expected_value=expected_tot,
                            actual_value=actual_tot,
                            severity=DefectSeverity.HIGH,
                            message=(
                                f"Line item #{i + 1} calculation error: "
                                f"{q} x {p} = {expected_tot} != total {actual_tot} [diff: {diff:.2f}]"
                            ),
                        )
                    )

        return math_defects

    def _record_defects(
        self, document_id: str, defects: List[DefectRecord]
    ) -> None:
        """Stores defects in registry and emits execution logs."""
        self._document_results[document_id] = defects
        self.defects.extend(defects)
        if defects:
            logger.warning(
                "Document '%s' evaluated with %d defects: %s",
                document_id,
                len(defects),
                [f"{d.defect_type.value}:{d.field_path}" for d in defects],
            )
        else:
            logger.info("Document '%s' evaluated clean (0 defects).", document_id)

    def evaluate_batch(
        self, test_cases: List[Dict[str, Any]]
    ) -> EvaluationSummary:
        """
        Evaluates a batch of test cases, each containing:
        - 'document_id': str
        - 'predicted': Invoice | dict | None
        - 'ground_truth': Invoice | dict
        """
        self.clear()
        for tc in test_cases:
            self.evaluate_document(
                document_id=tc["document_id"],
                predicted=tc.get("predicted"),
                ground_truth=tc["ground_truth"],
            )
        return self.get_summary()

    def get_summary(self) -> EvaluationSummary:
        """Computes aggregate defect metrics and success rates."""
        total_docs = len(self._document_results)
        perfect_docs = sum(
            1 for d in self._document_results.values() if len(d) == 0
        )
        defective_docs = total_docs - perfect_docs
        total_defs = len(self.defects)

        by_type = {dt.value: 0 for dt in DefectType}
        for d in self.defects:
            by_type[d.defect_type.value] += 1

        by_sev = {ds.value: 0 for ds in DefectSeverity}
        for d in self.defects:
            by_sev[d.severity.value] += 1

        doc_acc = (perfect_docs / total_docs * 100.0) if total_docs > 0 else 0.0

        total_fields_estimated = max(1, total_docs * 10)
        field_acc = max(
            0.0, 100.0 - (total_defs / total_fields_estimated) * 100.0
        )

        return EvaluationSummary(
            total_documents=total_docs,
            perfect_documents=perfect_docs,
            defective_documents=defective_docs,
            total_defects=total_defs,
            defects_by_type=by_type,
            defects_by_severity=by_sev,
            document_accuracy_rate=round(doc_acc, 2),
            field_accuracy_rate=round(field_acc, 2),
        )

    def generate_markdown_report(self) -> str:
        """Renders an evaluation report formatted in GitHub Flavored Markdown."""
        summary = self.get_summary()

        lines: List[str] = [
            "# Invoice Extraction Evaluation & Defect Report",
            f"**Generated:** {summary.timestamp}",
            "",
            "## Summary Metrics",
            f"- **Total Documents Evaluated:** {summary.total_documents}",
            f"- **Perfect Extractions (0 Defects):** {summary.perfect_documents}",
            f"- **Defective Documents:** {summary.defective_documents}",
            f"- **Document-Level Accuracy:** {summary.document_accuracy_rate}%",
            f"- **Estimated Field Accuracy:** {summary.field_accuracy_rate}%",
            f"- **Total Defect Instances:** {summary.total_defects}",
            "",
            "## Defects by Canonical Category",
            "| Defect Category | Count | Description |",
            "|---|---|---|",
            f"| `field_missing` | {summary.defects_by_type.get('field_missing', 0)} | Expected field or line item missing/null |",
            f"| `ocr_misrecognition` | {summary.defects_by_type.get('ocr_misrecognition', 0)} | Character confusion, typos, or noisy text |",
            f"| `decimal_misalignment` | {summary.defects_by_type.get('decimal_misalignment', 0)} | Power-of-10 shifted values (e.g. 10x, 100x) |",
            f"| `mathematical_discrepancy` | {summary.defects_by_type.get('mathematical_discrepancy', 0)} | Line item products or subtotal+tax sum errors |",
            "",
            "## Defects by Severity",
            f"- **Critical:** {summary.defects_by_severity.get('critical', 0)}",
            f"- **High:** {summary.defects_by_severity.get('high', 0)}",
            f"- **Medium:** {summary.defects_by_severity.get('medium', 0)}",
            f"- **Low:** {summary.defects_by_severity.get('low', 0)}",
            "",
            "## Detailed Defect Log",
        ]

        if not self.defects:
            lines.extend(
                [
                    "> [!NOTE]",
                    "> All evaluated documents passed with zero defects.",
                ]
            )
        else:
            lines.extend(
                [
                    "| ID | Document | Category | Path | Expected | Actual | Severity | Diagnostic |",
                    "|---|---|---|---|---|---|---|---|",
                ]
            )
            for d in self.defects:
                exp_clean = (
                    str(d.expected_value).replace("|", "\\|").replace("\n", " ")
                )
                act_clean = (
                    str(d.actual_value).replace("|", "\\|").replace("\n", " ")
                )
                msg_clean = d.message.replace("|", "\\|")
                lines.append(
                    f"| `{d.defect_id}` | `{d.document_id}` | `{d.defect_type.value}` | `{d.field_path}` "
                    f"| `{exp_clean}` | `{act_clean}` | **{d.severity.value}** | {msg_clean} |"
                )

        return "\n".join(lines)

    def export_report(self, output_path: Union[str, Path]) -> Path:
        """Exports the markdown report to disk."""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        report_md = self.generate_markdown_report()
        target.write_text(report_md, encoding="utf-8")
        logger.info("Evaluation report exported to: %s", target)
        return target

