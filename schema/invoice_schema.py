"""
Invoice Schema Definitions (Pydantic v2)
========================================
Defines strict, validated data structures for invoice extraction pipelines.
Includes mathematical discrepancy detection across line items, subtotals,
tax amounts, and grand totals.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)


class MathematicalDiscrepancyError(ValueError):
    """Raised when arithmetic validation fails for invoice amounts."""
    pass


def _to_decimal(val: float | int | str | None) -> Decimal:
    """Helper to convert numeric values to Decimal for precise financial comparison."""
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class LineItem(BaseModel):
    """
    Individual line item extracted from an invoice table.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )

    description: str = Field(
        ...,
        min_length=1,
        description="Text description of the product or service billed.",
    )
    quantity: float = Field(
        ...,
        gt=0,
        description="Quantity of units billed (must be greater than 0).",
    )
    unit_price: float = Field(
        ...,
        ge=0,
        description="Price charged per single unit (must be non-negative).",
    )
    total: float = Field(
        ...,
        ge=0,
        description="Total billed amount for this line item (quantity * unit_price).",
    )

    @model_validator(mode="after")
    def validate_line_item_math(self, info: ValidationInfo) -> LineItem:
        """Validates that quantity * unit_price matches the line item total."""
        strict = True
        if info.context and isinstance(info.context, dict):
            strict = info.context.get("strict_math", True)

        qty_dec = Decimal(str(self.quantity))
        price_dec = _to_decimal(self.unit_price)
        expected_total = (qty_dec * price_dec).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        actual_total = _to_decimal(self.total)

        tolerance = Decimal("0.02")
        diff = abs(expected_total - actual_total)

        if diff > tolerance and strict:
            raise MathematicalDiscrepancyError(
                f"Line item '{self.description}' arithmetic mismatch: quantity ("
                f"{self.quantity}) * unit_price ({self.unit_price}) = {expected_total} "
                f"does not match total ({actual_total}) [diff: {diff:.2f}]"
            )
        return self

    def check_discrepancy(self, tolerance: float = 0.02) -> Optional[str]:
        """Inspection helper returning discrepancy message without raising."""
        qty_dec = Decimal(str(self.quantity))
        price_dec = _to_decimal(self.unit_price)
        expected_total = (qty_dec * price_dec).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        actual_total = _to_decimal(self.total)
        diff = abs(expected_total - actual_total)
        if diff > Decimal(str(tolerance)):
            return (
                f"Line item '{self.description}' discrepancy: "
                f"{self.quantity} x {self.unit_price} = {expected_total:.2f} != {actual_total:.2f}"
            )
        return None


class Invoice(BaseModel):
    """
    Strict Pydantic v2 data model representing a fully structured invoice.
    Enforces deterministic validation and mathematical integrity.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
        json_schema_extra={
            "description": "Structured invoice extraction output schema."
        },
    )

    vendor_name: str = Field(
        ...,
        min_length=1,
        description="Name of the merchant, organization, or supplier issuing the invoice.",
    )
    invoice_date: Optional[str] = Field(
        default=None,
        description="Date of invoice issuance in ISO YYYY-MM-DD or document format.",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Payment due date in ISO YYYY-MM-DD or document format.",
    )
    line_items: List[LineItem] = Field(
        default_factory=list,
        description="List of individual line items, charges, or services.",
    )
    subtotal: Optional[float] = Field(
        default=None,
        ge=0,
        description="Subtotal amount before taxes and discounts.",
    )
    tax_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Total tax amount applied to the invoice.",
    )
    grand_total: float = Field(
        ...,
        ge=0,
        description="Final payable grand total (subtotal + tax).",
    )

    @model_validator(mode="after")
    def validate_invoice_math(self, info: ValidationInfo) -> Invoice:
        """
        Validates internal invoice arithmetic:
        1. subtotal + tax_amount == grand_total (when subtotal and tax are provided)
        2. sum(line_items.total) == subtotal (when line items and subtotal are provided)
        """
        strict = True
        if info.context and isinstance(info.context, dict):
            strict = info.context.get("strict_math", True)

        discrepancies = self.find_mathematical_discrepancies()
        if discrepancies and strict:
            raise MathematicalDiscrepancyError(
                f"Mathematical discrepancies found: {'; '.join(discrepancies)}"
            )
        return self

    def find_mathematical_discrepancies(self, tolerance: float = 0.02) -> List[str]:
        """
        Calculates all mathematical discrepancies across header totals and line items.
        Returns a list of human-readable diagnostic messages.
        """
        discrepancies: List[str] = []
        tol = Decimal(str(tolerance))

        # 1. Header arithmetic check (subtotal + tax vs grand_total)
        if self.subtotal is not None and self.tax_amount is not None:
            expected_grand = _to_decimal(self.subtotal) + _to_decimal(self.tax_amount)
            actual_grand = _to_decimal(self.grand_total)
            diff = abs(expected_grand - actual_grand)
            if diff > tol:
                discrepancies.append(
                    f"Subtotal ({_to_decimal(self.subtotal):.2f}) + Tax ({_to_decimal(self.tax_amount):.2f}) = "
                    f"{expected_grand:.2f} does not match Grand Total ({actual_grand:.2f}) [diff: {diff:.2f}]"
                )

        # 2. Line items sum check
        if self.line_items:
            sum_line_items = sum(_to_decimal(item.total) for item in self.line_items)
            if self.subtotal is not None:
                actual_subtotal = _to_decimal(self.subtotal)
                diff = abs(sum_line_items - actual_subtotal)
                if diff > tol:
                    discrepancies.append(
                        f"Sum of line items ({sum_line_items:.2f}) does not match subtotal "
                        f"({actual_subtotal:.2f}) [diff: {diff:.2f}]"
                    )
            elif self.tax_amount is None:
                actual_grand = _to_decimal(self.grand_total)
                diff = abs(sum_line_items - actual_grand)
                if diff > tol:
                    discrepancies.append(
                        f"Sum of line items ({sum_line_items:.2f}) does not match grand total "
                        f"({actual_grand:.2f}) [diff: {diff:.2f}]"
                    )

        # 3. Individual line item checks
        for idx, item in enumerate(self.line_items):
            item_disc = item.check_discrepancy(tolerance=tolerance)
            if item_disc:
                discrepancies.append(f"Line item #{idx + 1}: {item_disc}")

        return discrepancies

    def to_deterministic_json(self, indent: int = 2) -> str:
        """
        Serializes the invoice model to deterministic, alphabetically-sorted JSON.
        Guarantees reproducible output format across platforms and engines.
        """
        data = self.model_dump()
        return json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=False)

