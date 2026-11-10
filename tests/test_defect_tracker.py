"""
Unit Tests for evals/defect_tracker.py
"""

from evals.defect_tracker import (
    DefectSeverity,
    DefectTracker,
    DefectType,
)


def test_field_missing_detection():
    """Verify missing required and optional fields are flagged."""
    tracker = DefectTracker()
    gt = {
        "vendor_name": "Nexus Software Inc",
        "grand_total": 1296.0,
        "due_date": "2026-10-31",
    }
    pred = {
        "vendor_name": None,  # Missing required
        "grand_total": 1296.0,
        "due_date": "",  # Missing optional
    }
    defects = tracker.evaluate_document("test_doc", pred, gt)
    missing_defects = [
        d for d in defects if d.defect_type == DefectType.FIELD_MISSING
    ]
    assert len(missing_defects) == 2

    paths = [d.field_path for d in missing_defects]
    assert "vendor_name" in paths
    assert "due_date" in paths


def test_decimal_misalignment_detection():
    """Verify power-of-10 decimal shifts are classified as decimal_misalignment."""
    tracker = DefectTracker()
    gt = {
        "vendor_name": "Apex Cloud",
        "grand_total": 45.0,
        "line_items": [
            {
                "description": "Service",
                "quantity": 1.0,
                "unit_price": 45.0,
                "total": 45.0,
            }
        ],
    }
    pred = {
        "vendor_name": "Apex Cloud",
        "grand_total": 450.0,  # 10x shift
        "line_items": [
            {
                "description": "Service",
                "quantity": 1.0,
                "unit_price": 450.0,  # 10x shift
                "total": 450.0,
            }
        ],
    }
    defects = tracker.evaluate_document("test_doc", pred, gt)
    decimal_defects = [
        d for d in defects if d.defect_type == DefectType.DECIMAL_MISALIGNMENT
    ]
    assert len(decimal_defects) >= 2


def test_ocr_misrecognition_detection():
    """Verify typographical and character errors are classified as ocr_misrecognition."""
    tracker = DefectTracker()
    gt = {
        "vendor_name": "Metro Express Mart",
        "invoice_date": "2026-10-20",
        "grand_total": 50.88,
    }
    pred = {
        "vendor_name": "Metro Expres Mart",  # Typo
        "invoice_date": "2026-10-28",  # Number noise
        "grand_total": 50.88,
    }
    defects = tracker.evaluate_document("test_doc", pred, gt)
    ocr_defects = [
        d for d in defects if d.defect_type == DefectType.OCR_MISRECOGNITION
    ]
    assert len(ocr_defects) == 2


def test_mathematical_discrepancy_detection():
    """Verify arithmetic mismatch in prediction is classified as mathematical_discrepancy."""
    tracker = DefectTracker()
    gt = {
        "vendor_name": "Cafe",
        "subtotal": 28.5,
        "tax_amount": 2.35,
        "grand_total": 30.85,
    }
    pred = {
        "vendor_name": "Cafe",
        "subtotal": 28.5,
        "tax_amount": 2.35,
        "grand_total": 35.0,  # Math mismatch
    }
    defects = tracker.evaluate_document("test_doc", pred, gt)
    math_defects = [
        d for d in defects if d.defect_type == DefectType.MATHEMATICAL_DISCREPANCY
    ]
    assert len(math_defects) >= 1
    assert math_defects[0].field_path == "grand_total"


def test_markdown_report_generation():
    """Verify markdown report renders GitHub flavored markdown tables and summary."""
    tracker = DefectTracker()
    gt = {"vendor_name": "Clean Corp", "grand_total": 100.0}
    pred = {"vendor_name": "Clean Corp", "grand_total": 100.0}
    tracker.evaluate_document("doc_01", pred, gt)

    report = tracker.generate_markdown_report()
    assert "# Invoice Extraction Evaluation & Defect Report" in report
    assert "All evaluated documents passed with zero defects." in report

    summary = tracker.get_summary()
    assert summary.total_documents == 1
    assert summary.perfect_documents == 1
    assert summary.document_accuracy_rate == 100.0

