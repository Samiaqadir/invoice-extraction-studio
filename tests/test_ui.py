"""
Unit Tests for ui/app.py, ui/converter.py, and ui/confidence.py
"""

import io
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from ui.app import app
from ui.confidence import compute_confidence_scores, evaluate_invoice_math
from ui.converter import (
    create_fallback_text_image,
    get_document_page_count,
    is_image_blank,
    render_document_to_pil,
    render_document_to_png_bytes,
)
from ui.exporter import invoice_to_csv_string

client = TestClient(app)


def test_index_page():
    """Verify HTML index page is served."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Invoice Extraction Studio" in response.text


def test_list_documents():
    """Verify API returns the test pack documents list."""
    response = client.get("/api/documents")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) >= 8
    doc_names = [d["name"] for d in docs]
    assert "doc_01_clean_digital_single_item.pdf" in doc_names
    assert "doc_03_photo_crumpled_receipt.png" in doc_names


def test_document_preview_rendering():
    """Verify PDF rendering to PNG preview endpoint returns non-empty image."""
    response = client.get("/api/document/doc_01_clean_digital_single_item.pdf/preview?page_idx=0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1000

    # Verify PNG bytes can be loaded by PIL and is not blank
    img = Image.open(io.BytesIO(response.content))
    assert img.size[0] > 0
    assert img.size[1] > 0
    assert not is_image_blank(img)


def test_converter_multi_tier():
    """Verify converter handles PDFs and images cleanly without blank frames."""
    pdf_path = Path("test_pack/doc_02_clean_digital_multi_item.pdf")
    img_pdf = render_document_to_pil(pdf_path)
    assert not is_image_blank(img_pdf)
    assert img_pdf.mode == "RGB"

    png_path = Path("test_pack/doc_03_photo_crumpled_receipt.png")
    img_png = render_document_to_pil(png_path)
    assert not is_image_blank(img_png)
    assert img_png.mode == "RGB"


def test_converter_fallback_text():
    """Verify fallback text layout generator creates a crisp non-blank preview."""
    fallback_img = create_fallback_text_image(
        Path("test_pack/doc_01_clean_digital_single_item.pdf")
    )
    assert not is_image_blank(fallback_img)
    assert fallback_img.size == (1000, 1400)


def test_document_upload_and_preview():
    """Verify file upload endpoint handles new PDFs and lists them."""
    test_pdf_content = Path("test_pack/doc_01_clean_digital_single_item.pdf").read_bytes()
    upload_res = client.post(
        "/api/upload",
        files={"file": ("custom_test_upload.pdf", test_pdf_content, "application/pdf")},
    )
    assert upload_res.status_code == 200
    data = upload_res.json()
    assert data["name"] == "custom_test_upload.pdf"

    # Verify preview works for uploaded file
    preview_res = client.get("/api/document/custom_test_upload.pdf/preview")
    assert preview_res.status_code == 200
    assert preview_res.headers["content-type"] == "image/png"


def test_extract_and_confidence_scoring():
    """Verify document extraction returns Pydantic data and confidence scoring."""
    response = client.post(
        "/api/extract",
        json={
            "document_name": "doc_01_clean_digital_single_item.pdf",
            "engine": "local_ocr",
            "re_extract": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "invoice_data" in data
    assert "confidence" in data
    assert "page_count" in data

    conf = data["confidence"]
    assert conf["overall_score"] >= 80.0
    assert conf["overall_badge"] in ("green", "amber", "red")
    assert "vendor_name" in conf["field_scores"]
    assert "grand_total" in conf["field_scores"]


def test_validate_mathematical_discrepancy():
    """Verify real-time validation catches subtotal + tax != grand_total."""
    bad_data = {
        "vendor_name": "Acme Corp",
        "invoice_date": "2026-10-01",
        "due_date": "2026-10-31",
        "line_items": [
            {
                "description": "Item 1",
                "quantity": 2.0,
                "unit_price": 50.0,
                "total": 100.0,
            }
        ],
        "subtotal": 100.0,
        "tax_amount": 10.0,
        "grand_total": 130.0,  # Expected 110.0 (diff 20.0)
    }
    response = client.post(
        "/api/validate",
        json={
            "document_name": "test_doc.pdf",
            "invoice_data": bad_data,
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["is_valid"] is False
    assert result["confidence"]["field_scores"]["grand_total"]["badge"] == "red"
    assert len(result["confidence"]["math_eval"]["alerts"]) >= 1


def test_export_csv_and_json():
    """Verify CSV and JSON export endpoints produce valid downloadable payloads."""
    payload = {
        "document_name": "doc_01_clean_digital_single_item.pdf",
        "invoice_data": {
            "vendor_name": "Nexus Software Inc",
            "invoice_date": "2026-10-01",
            "due_date": "2026-10-31",
            "line_items": [
                {
                    "description": "Annual SaaS",
                    "quantity": 1.0,
                    "unit_price": 1200.0,
                    "total": 1200.0,
                }
            ],
            "subtotal": 1200.0,
            "tax_amount": 96.0,
            "grand_total": 1296.0,
        },
    }

    # CSV Export
    res_csv = client.post("/api/export/csv", json=payload)
    assert res_csv.status_code == 200
    assert "vendor_name,invoice_date,due_date" in res_csv.text
    assert "Nexus Software Inc" in res_csv.text

    # JSON Export
    res_json = client.post("/api/export/json", json=payload)
    assert res_json.status_code == 200
    json_data = res_json.json()
    assert json_data["vendor_name"] == "Nexus Software Inc"
    assert json_data["grand_total"] == 1296.0
