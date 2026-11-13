"""
Unit & Integration Tests for Non-Invoice Guardrails and Bounding Boxes
======================================================================
Tests:
- Non-invoice domain rejection (resumes, memos, random text, empty files).
- HTTP 422 guardrails error handling in FastAPI endpoints.
- Normalized bounding box extraction and degraded scan fallback states.
- Date extraction regex fix on pipe-delimited single-line headers.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from pipeline.extractor import (
    NonInvoiceDocumentError,
    extract_invoice,
    extract_invoice_with_metadata,
    validate_invoice_domain,
)
from schema.invoice_schema import Invoice
from ui.app import app

client = TestClient(app)
ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_PACK_DIR = ROOT_DIR / "test_pack"


def test_resume_document_rejected(tmp_path: Path):
    """Verifies that a resume or CV is detected and rejected upfront."""
    resume_text = (
        "Curriculum Vitae\n"
        "Jane Doe, Senior Software Architect\n"
        "Education: Bachelor of Science in Computer Science (GPA: 3.9)\n"
        "Work Experience: 10 years distributed systems engineering\n"
        "Skills: Python, FastAPI, Docker, Kubernetes\n"
        "Certifications: AWS Certified Solutions Architect\n"
        "References available upon request."
    )
    is_valid, reason, code = validate_invoice_domain(resume_text, tables=[])
    assert is_valid is False
    assert code == "RESUME_DOCUMENT"
    assert "resume or CV" in reason

    resume_file = tmp_path / "resume_sample.txt"
    resume_file.write_text(resume_text, encoding="utf-8")

    # In extractor, should raise NonInvoiceDocumentError
    with pytest.raises(NonInvoiceDocumentError) as exc_info:
        extract_invoice(resume_file, engine="local_ocr")
    assert exc_info.value.reason == "RESUME_DOCUMENT"


def test_memo_document_rejected(tmp_path: Path):
    """Verifies that internal corporate memos are rejected."""
    memo_text = (
        "MEMORANDUM\n"
        "TO: All Staff Members\n"
        "FROM: Facilities Operations Management\n"
        "SUBJECT: Upcoming Office Electrical Maintenance and IT Downtime\n"
        "Meeting Minutes: The power generators will undergo maintenance this Sunday."
    )
    is_valid, reason, code = validate_invoice_domain(memo_text, tables=[])
    assert is_valid is False
    assert code == "MEMO_DOCUMENT"
    assert "internal memorandum" in reason

    memo_file = tmp_path / "memo_sample.txt"
    memo_file.write_text(memo_text, encoding="utf-8")

    with pytest.raises(NonInvoiceDocumentError) as exc_info:
        extract_invoice(memo_file, engine="local_ocr")
    assert exc_info.value.reason == "MEMO_DOCUMENT"


def test_empty_document_rejected():
    """Verifies that blank or whitespace-only documents are rejected."""
    is_valid, reason, code = validate_invoice_domain("   \n\t  ", tables=[])
    assert is_valid is False
    assert code == "EMPTY_DOCUMENT"


def test_valid_invoices_pass_guardrails():
    """Ensures all benchmark test invoices pass domain guardrails."""
    for doc in (
        "doc_01_clean_digital_single_item.pdf",
        "doc_02_clean_digital_multi_item.pdf",
        "doc_03_photo_crumpled_receipt.png",
        "doc_04_photo_low_light_blurry.png",
        "doc_05_missing_tax_field.pdf",
        "doc_06_missing_dates_partial.pdf",
        "doc_07_complex_multi_page_table.pdf",
        "doc_08_decimal_edge_case.png",
    ):
        p = TEST_PACK_DIR / doc
        assert p.exists(), f"Missing test file {doc}"
        inv = extract_invoice(p, engine="local_ocr")
        assert isinstance(inv, Invoice)
        assert inv.grand_total > 0


def test_pipe_delimited_date_disambiguation():
    """Ensures single-line pipe-delimited dates extract both invoice_date and due_date accurately."""
    doc_path = TEST_PACK_DIR / "doc_01_clean_digital_single_item.pdf"
    inv = extract_invoice(doc_path, engine="local_ocr")
    assert inv.invoice_date == "2026-10-01"
    assert inv.due_date == "2026-10-31"


def test_bounding_boxes_and_degraded_regions():
    """Verifies bounding box metadata generation and degraded state detection."""
    # 1. Clean PDF bounding boxes
    pdf_path = TEST_PACK_DIR / "doc_01_clean_digital_single_item.pdf"
    res_pdf = extract_invoice_with_metadata(pdf_path, engine="local_ocr")
    assert "bounding_boxes" in res_pdf
    assert len(res_pdf["bounding_boxes"]) >= 6
    assert any(b["field"] == "vendor_name" for b in res_pdf["bounding_boxes"])
    assert any(b["field"] == "grand_total" for b in res_pdf["bounding_boxes"])

    # 2. Degraded receipt (crumpled / photo)
    photo_path = TEST_PACK_DIR / "doc_03_photo_crumpled_receipt.png"
    res_photo = extract_invoice_with_metadata(photo_path, engine="local_ocr")
    assert res_photo["is_degraded"] is True
    assert len(res_photo["degraded_regions"]) > 0
    assert any(b["status"] in ("degraded", "fallback") for b in res_photo["bounding_boxes"])


def test_api_extract_non_invoice_returns_422(tmp_path: Path):
    """Verifies that FastAPI /api/extract returns HTTP 422 JSON on non-invoice files."""
    # Place a non-invoice file in outputs/uploads
    uploads_dir = ROOT_DIR / "outputs" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    resume_file = uploads_dir / "test_candidate_resume.txt"
    resume_file.write_text(
        "Curriculum Vitae\nCandidate: Alex Mercer\nEducation: Bachelor of Science\nWork Experience: 5 years",
        encoding="utf-8",
    )

    response = client.post(
        "/api/extract",
        json={"document_name": "test_candidate_resume.txt", "engine": "local_ocr"},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["error"] == "NON_INVOICE_DOCUMENT"
    assert "resume or CV" in payload["message"]

