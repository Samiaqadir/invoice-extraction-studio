"""
FastAPI Web Application for Invoice Extraction Studio
=====================================================
Lightweight, high-performance web interface providing:
- Robust multi-tier document conversion (pypdfium2, pdfplumber, PIL text fallback).
- Side-by-side original invoice viewer (PDF/Image) and extracted editable Pydantic form.
- Real-time confidence scoring & color indicators (Green, Amber, Red).
- Zero-latency client-side & server-side inline editing and arithmetic validation.
- Instant JSON and CSV export endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline.extractor import (
    NonInvoiceDocumentError,
    extract_invoice,
    extract_invoice_with_metadata,
)
from schema.invoice_schema import Invoice
from ui.confidence import compute_confidence_scores, evaluate_invoice_math
from ui.converter import (
    get_document_page_count,
    render_document_to_pil,
    render_document_to_png_bytes,
)
from ui.exporter import export_invoice_files, invoice_to_csv_string

logger = logging.getLogger("ui.app")

ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_PACK_DIR = ROOT_DIR / "test_pack"
OUTPUTS_DIR = ROOT_DIR / "outputs"
UPLOADS_DIR = OUTPUTS_DIR / "uploads"
UI_ASSETS_DIR = ROOT_DIR / "ui_assets"
STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
UI_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Invoice Extraction Studio",
    description="Interactive Human-in-the-Loop Invoice Extraction & Auditing Studio",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    document_name: str
    engine: str = "auto"
    re_extract: bool = False


class ValidationRequest(BaseModel):
    document_name: str
    invoice_data: Dict[str, Any]


class SaveRequest(BaseModel):
    document_name: str
    invoice_data: Dict[str, Any]


def _resolve_document_path(doc_name: str) -> Path:
    """Finds document across test_pack, uploads, and outputs."""
    candidates = [
        TEST_PACK_DIR / doc_name,
        UPLOADS_DIR / doc_name,
        OUTPUTS_DIR / doc_name,
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    raise HTTPException(status_code=404, detail=f"Document '{doc_name}' not found.")


@app.get("/api/documents")
def list_documents() -> List[Dict[str, Any]]:
    """Lists benchmark test pack documents and uploaded files."""
    docs = []
    seen = set()

    # 1. Test pack documents
    if TEST_PACK_DIR.exists():
        for f in sorted(TEST_PACK_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
                seen.add(f.name)
                docs.append(
                    {
                        "name": f.name,
                        "size_kb": round(f.stat().st_size / 1024.0, 1),
                        "format": f.suffix.lower().replace(".", "").upper(),
                        "pages": get_document_page_count(f),
                        "source": "benchmark",
                    }
                )

    # 2. Uploaded documents
    if UPLOADS_DIR.exists():
        for f in sorted(UPLOADS_DIR.iterdir()):
            if f.is_file() and f.name not in seen and f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
                seen.add(f.name)
                docs.append(
                    {
                        "name": f.name,
                        "size_kb": round(f.stat().st_size / 1024.0, 1),
                        "format": f.suffix.lower().replace(".", "").upper(),
                        "pages": get_document_page_count(f),
                        "source": "uploaded",
                    }
                )
    return docs


@app.get("/api/document/{doc_name}/preview")
def get_document_preview(
    doc_name: str,
    page_idx: int = Query(default=0, ge=0),
    scale: float = Query(default=2.0, ge=1.0, le=4.0),
    refresh: bool = False,
):
    """
    Renders any PDF page or image as a high-resolution, non-blank PNG image.
    Uses multi-tier fallback (pypdfium2 -> pdfplumber -> PIL synthetic layout).
    """
    target = _resolve_document_path(doc_name)
    try:
        png_bytes = render_document_to_png_bytes(
            target, page_idx=page_idx, scale=scale, force_refresh=refresh
        )
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache" if refresh else "public, max-age=3600",
                "X-Document-Pages": str(get_document_page_count(target)),
            },
        )
    except Exception as e:
        logger.error("Preview rendering failed for '%s': %s", doc_name, e)
        raise HTTPException(
            status_code=500, detail=f"Document rendering failure: {e}"
        )


@app.get("/api/document/{doc_name}/file")
def get_document_file(doc_name: str):
    """Streams the raw file (PDF or image) for direct download or browser preview."""
    target = _resolve_document_path(doc_name)
    if target.suffix.lower() == ".pdf":
        mime = "application/pdf"
    elif target.suffix.lower() == ".txt":
        mime = "text/plain"
    else:
        mime = f"image/{target.suffix.lower().replace('.', '')}"
    return FileResponse(target, media_type=mime)


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Uploads a custom invoice file (PDF or Image) for review with non-invoice guardrails."""
    filename = Path(file.filename).name
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{suffix}'. Allowed: PDF, PNG, JPG, WEBP, TXT.",
        )

    target_path = UPLOADS_DIR / filename
    with open(target_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = target_path.stat().st_size
    if file_size == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty (0 bytes). Please upload a valid document.",
        )
    if file_size > 50 * 1024 * 1024:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="File size exceeds maximum permitted limit (50 MB).",
        )

    return {
        "status": "success",
        "name": filename,
        "size_kb": round(file_size / 1024.0, 1),
        "pages": get_document_page_count(target_path),
    }


@app.post("/api/extract")
def extract_document(req: ExtractRequest):
    """
    Extracts invoice entities and generates normalized bounding box metadata.
    Enforces non-invoice rejection guardrails (HTTP 422) with zero application crashes.
    """
    doc_path = _resolve_document_path(req.document_name)

    try:
        meta_res = extract_invoice_with_metadata(
            doc_path,
            engine=req.engine,
            save_output=True,
            strict_math=False,
            output_dir=OUTPUTS_DIR,
        )
        invoice_dict = meta_res["invoice_data"]
        bounding_boxes = meta_res["bounding_boxes"]
        degraded_regions = meta_res["degraded_regions"]
        is_degraded = meta_res["is_degraded"]
    except NonInvoiceDocumentError as nide:
        logger.warning(
            "Document '%s' rejected by guardrails: %s (%s)",
            req.document_name,
            nide,
            nide.reason,
        )
        return JSONResponse(
            status_code=422,
            content={
                "status": "rejected",
                "error": "NON_INVOICE_DOCUMENT",
                "reason": nide.reason,
                "message": str(nide),
                "detected_type": nide.detected_type,
            },
        )
    except Exception as e:
        logger.error("Extraction error for '%s': %s", req.document_name, e)
        raise HTTPException(status_code=500, detail=f"Extraction failure: {e}")

    confidence_data = compute_confidence_scores(
        invoice_dict, extraction_engine=req.engine
    )

    return {
        "status": "success",
        "document_name": doc_path.name,
        "page_count": get_document_page_count(doc_path),
        "invoice_data": invoice_dict,
        "confidence": confidence_data,
        "bounding_boxes": bounding_boxes,
        "degraded_regions": degraded_regions,
        "is_degraded": is_degraded,
    }


@app.post("/api/validate")
def validate_invoice_payload(req: ValidationRequest) -> Dict[str, Any]:
    """Validates editable form payload in real-time and computes discrepancy alerts."""
    data = req.invoice_data
    conf_scores = compute_confidence_scores(data)

    pydantic_error: Optional[str] = None
    try:
        Invoice.model_validate(data, context={"strict_math": False})
    except Exception as e:
        pydantic_error = str(e)

    return {
        "is_valid": conf_scores["math_eval"]["is_arithmetically_valid"]
        and pydantic_error is None,
        "confidence": conf_scores,
        "pydantic_error": pydantic_error,
    }


@app.post("/api/export/csv")
def export_csv(req: ValidationRequest):
    """Exports currently edited invoice to CSV."""
    csv_text = invoice_to_csv_string(req.invoice_data)
    filename = f"{Path(req.document_name).stem}_reviewed.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/export/json")
def export_json(req: ValidationRequest):
    """Exports currently edited invoice to formatted JSON."""
    try:
        inv = Invoice.model_validate(req.invoice_data, context={"strict_math": False})
        json_text = inv.to_deterministic_json(indent=2)
    except Exception:
        json_text = json.dumps(req.invoice_data, indent=2)

    filename = f"{Path(req.document_name).stem}_reviewed.json"
    return Response(
        content=json_text,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/save")
def save_reviewed_invoice(req: SaveRequest) -> Dict[str, Any]:
    """Persists reviewed invoice files and updates audit log."""
    saved = export_invoice_files(
        req.invoice_data, req.document_name, output_dir=OUTPUTS_DIR
    )
    conf = compute_confidence_scores(req.invoice_data)

    log_file = UI_ASSETS_DIR / "validation_logs.json"
    logs = []
    if log_file.exists():
        try:
            logs = json.loads(log_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    logs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "document_id": req.document_name,
            "overall_confidence": conf["overall_score"],
            "status": conf["overall_status"],
            "math_verified": conf["math_eval"]["is_arithmetically_valid"],
            "vendor_name": req.invoice_data.get("vendor_name"),
            "grand_total": req.invoice_data.get("grand_total"),
        }
    )
    log_file.write_text(json.dumps(logs, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "json_file": str(saved["json"].name),
        "csv_file": str(saved["csv"].name),
    }


@app.get("/", response_class=HTMLResponse)
def index_page():
    index_html_path = TEMPLATES_DIR / "index.html"
    return HTMLResponse(content=index_html_path.read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
