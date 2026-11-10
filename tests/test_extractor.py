"""
Unit Tests for pipeline/extractor.py
"""

from pathlib import Path
import pytest

from pipeline.extractor import (
    InvoiceExtractor,
    extract_invoice,
)
from schema.invoice_schema import Invoice


def test_file_type_detection(tmp_path):
    """Verify supported and unsupported extensions are correctly identified."""
    extractor = InvoiceExtractor(output_dir=tmp_path)

    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock")
    assert extractor._detect_file_type(pdf_file) == "application/pdf"

    png_file = tmp_path / "invoice.png"
    png_file.write_bytes(b"\x89PNG mock")
    assert extractor._detect_file_type(png_file) == "image/png"

    # Unsupported format
    txt_file = tmp_path / "invoice.xyz"
    txt_file.write_text("dummy")
    with pytest.raises(ValueError):
        extractor._detect_file_type(txt_file)

    # Missing file
    missing = tmp_path / "missing.pdf"
    with pytest.raises(FileNotFoundError):
        extractor._detect_file_type(missing)


def test_parse_invoice_text_heuristic():
    """Verify regex and rule-based text parsing into Invoice dictionary."""
    extractor = InvoiceExtractor()
    sample_text = (
        "Acme Global Logistics Inc\n"
        "Invoice Date: 2026-10-15\n"
        "Due Date: 2026-11-15\n"
        "Freight Transportation Services 1.0 $1500.00 $1500.00\n"
        "Subtotal: $1500.00\n"
        "Tax: $120.00\n"
        "Grand Total: $1620.00\n"
    )
    parsed = extractor._parse_invoice_text(sample_text, tables=[])
    assert parsed["vendor_name"] == "Acme Global Logistics Inc"
    assert parsed["invoice_date"] == "2026-10-15"
    assert parsed["due_date"] == "2026-11-15"
    assert parsed["subtotal"] == 1500.0
    assert parsed["tax_amount"] == 120.0
    assert parsed["grand_total"] == 1620.0
    assert len(parsed["line_items"]) == 1
    assert parsed["line_items"][0]["description"] == "Freight Transportation Services"


def test_extract_invoice_local_ocr(tmp_path):
    """Verify extract_invoice with local OCR engine on real test pack PDF."""
    test_pdf = Path("test_pack/doc_01_clean_digital_single_item.pdf")
    if not test_pdf.exists():
        pytest.skip("Test pack doc_01 not found.")

    invoice = extract_invoice(
        document_path=test_pdf,
        engine="local_ocr",
        save_output=True,
        output_dir=tmp_path,
    )
    assert isinstance(invoice, Invoice)
    assert invoice.vendor_name == "Nexus Software Inc"
    assert invoice.grand_total == 1296.0

    output_file = tmp_path / "doc_01_clean_digital_single_item_extracted.json"
    assert output_file.exists()

