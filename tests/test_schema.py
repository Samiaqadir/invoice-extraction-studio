"""
Unit Tests for schema/invoice_schema.py
"""

import json
import pytest
from pydantic import ValidationError

from schema.invoice_schema import (
    Invoice,
    LineItem,
    MathematicalDiscrepancyError,
)


def test_valid_invoice_creation():
    """Verify normal valid invoice parses and validates cleanly."""
    inv = Invoice(
        vendor_name="Nexus Software Inc",
        invoice_date="2026-10-01",
        due_date="2026-10-31",
        line_items=[
            LineItem(
                description="Annual Developer SaaS Subscription",
                quantity=1.0,
                unit_price=1200.0,
                total=1200.0,
            )
        ],
        subtotal=1200.0,
        tax_amount=96.0,
        grand_total=1296.0,
    )
    assert inv.vendor_name == "Nexus Software Inc"
    assert inv.grand_total == 1296.0
    assert len(inv.line_items) == 1
    assert inv.find_mathematical_discrepancies() == []


def test_deterministic_json_serialization():
    """Verify JSON output keys are sorted and format is deterministic."""
    inv = Invoice(
        vendor_name="Alpha Tech",
        invoice_date="2026-01-15",
        due_date=None,
        line_items=[],
        subtotal=100.0,
        tax_amount=0.0,
        grand_total=100.0,
    )
    raw_json = inv.to_deterministic_json()
    data = json.loads(raw_json)

    # Validate keys order matches sorted keys
    keys = list(data.keys())
    assert keys == sorted(keys)
    assert data["vendor_name"] == "Alpha Tech"
    assert data["due_date"] is None


def test_line_item_math_validation_strict():
    """Verify quantity * unit_price != total raises ValidationError in strict mode."""
    with pytest.raises(ValidationError) as exc_info:
        LineItem(
            description="Bad Item",
            quantity=2.0,
            unit_price=50.0,
            total=150.0,  # Expected 100.0
        )
    assert "arithmetic mismatch" in str(exc_info.value)


def test_line_item_math_validation_lenient():
    """Verify lenient mode allows instantiation but permits inspection."""
    item = LineItem.model_validate(
        {
            "description": "Lenient Item",
            "quantity": 2.0,
            "unit_price": 50.0,
            "total": 150.0,
        },
        context={"strict_math": False},
    )
    assert item.total == 150.0
    disc = item.check_discrepancy()
    assert disc is not None
    assert "discrepancy" in disc


def test_invoice_header_math_discrepancy():
    """Verify subtotal + tax != grand_total raises ValidationError in strict mode."""
    with pytest.raises(ValidationError) as exc_info:
        Invoice(
            vendor_name="Acme Corp",
            subtotal=100.0,
            tax_amount=10.0,
            grand_total=125.0,  # Expected 110.0
        )
    assert "Mathematical discrepancies found" in str(exc_info.value)


def test_invoice_line_items_sum_discrepancy():
    """Verify sum of line items != subtotal raises ValidationError in strict mode."""
    with pytest.raises(ValidationError) as exc_info:
        Invoice(
            vendor_name="Acme Corp",
            line_items=[
                LineItem(
                    description="Item A",
                    quantity=1.0,
                    unit_price=40.0,
                    total=40.0,
                )
            ],
            subtotal=100.0,  # Items sum to 40.0 != 100.0
            tax_amount=10.0,
            grand_total=110.0,
        )
    assert "Sum of line items" in str(exc_info.value)


def test_invoice_missing_tax_field_valid():
    """Verify invoices with tax_amount=None (tax exempt or 0%) pass when subtotal == grand_total."""
    inv = Invoice(
        vendor_name="Global Trade Logistics B.V.",
        invoice_date="2026-10-22",
        due_date="2026-10-22",
        line_items=[
            LineItem(
                description="Freight",
                quantity=1.0,
                unit_price=2450.0,
                total=2450.0,
            ),
            LineItem(
                description="Customs",
                quantity=1.0,
                unit_price=350.0,
                total=350.0,
            ),
        ],
        subtotal=2800.0,
        tax_amount=None,
        grand_total=2800.0,
    )
    assert inv.tax_amount is None
    assert inv.grand_total == 2800.0
    assert inv.find_mathematical_discrepancies() == []


def test_invoice_missing_dates_valid():
    """Verify invoices with null dates are accepted."""
    inv = Invoice(
        vendor_name="Apex Wholesale",
        invoice_date=None,
        due_date=None,
        line_items=[],
        subtotal=50.0,
        tax_amount=5.0,
        grand_total=55.0,
    )
    assert inv.invoice_date is None
    assert inv.due_date is None

