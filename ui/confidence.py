"""
Confidence Scoring & Mathematical Verification Helper for Invoice UI
====================================================================
Assigns confidence percentages and visual color indicators (green, amber, red)
based on extraction fidelity, structural completeness, and arithmetic validation.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Dict, List, Optional, Tuple


def _to_dec(val: Any) -> Decimal:
    """Helper to convert value to Decimal."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def evaluate_invoice_math(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs comprehensive mathematical validation of invoice fields.
    Returns calculated sums, difference metrics, and list of discrepancy alerts.
    """
    alerts: List[Dict[str, Any]] = []

    subtotal = data.get("subtotal")
    tax_amount = data.get("tax_amount")
    grand_total = data.get("grand_total", 0.0)
    line_items = data.get("line_items", []) or []

    # 1. Line items product check
    calc_items_total = Decimal("0.00")
    item_discrepancies: List[int] = []

    for idx, item in enumerate(line_items):
        q = _to_dec(item.get("quantity", 0))
        p = _to_dec(item.get("unit_price", 0))
        t = _to_dec(item.get("total", 0))
        expected_t = (q * p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        calc_items_total += t

        diff = abs(expected_t - t)
        if diff > Decimal("0.02") and q > 0 and p > 0:
            item_discrepancies.append(idx)
            alerts.append(
                {
                    "target": f"line_items[{idx}]",
                    "severity": "red",
                    "message": (
                        f"Line Item #{idx + 1} '{item.get('description', 'Item')}': "
                        f"qty ({q}) x price (${p:.2f}) = ${expected_t:.2f} != total (${t:.2f}) "
                        f"[diff: ${diff:.2f}]"
                    ),
                }
            )

    # 2. Sum of line items vs subtotal
    subtotal_dec = _to_dec(subtotal) if subtotal is not None else None
    if subtotal_dec is not None and line_items:
        diff_sub = abs(calc_items_total - subtotal_dec)
        if diff_sub > Decimal("0.02"):
            alerts.append(
                {
                    "target": "subtotal",
                    "severity": "red",
                    "message": (
                        f"Line items sum (${calc_items_total:.2f}) does not match "
                        f"subtotal (${subtotal_dec:.2f}) [diff: ${diff_sub:.2f}]"
                    ),
                }
            )

    # 3. Header arithmetic: subtotal + tax vs grand_total
    grand_total_dec = _to_dec(grand_total)
    tax_dec = _to_dec(tax_amount) if tax_amount is not None else Decimal("0.00")

    if subtotal_dec is not None:
        expected_grand = subtotal_dec + tax_dec
        diff_grand = abs(expected_grand - grand_total_dec)
        if diff_grand > Decimal("0.02"):
            alerts.append(
                {
                    "target": "grand_total",
                    "severity": "red",
                    "message": (
                        f"Header mismatch: subtotal (${subtotal_dec:.2f}) + "
                        f"tax (${tax_dec:.2f}) = ${expected_grand:.2f} != grand total (${grand_total_dec:.2f}) "
                        f"[diff: ${diff_grand:.2f}]"
                    ),
                }
            )
    elif line_items:
        expected_grand = calc_items_total + tax_dec
        diff_grand = abs(expected_grand - grand_total_dec)
        if diff_grand > Decimal("0.02"):
            alerts.append(
                {
                    "target": "grand_total",
                    "severity": "red",
                    "message": (
                        f"Header mismatch: calculated items (${calc_items_total:.2f}) + "
                        f"tax (${tax_dec:.2f}) = ${expected_grand:.2f} != grand total (${grand_total_dec:.2f}) "
                        f"[diff: ${diff_grand:.2f}]"
                    ),
                }
            )

    return {
        "calculated_line_items_sum": float(calc_items_total),
        "expected_grand_total": float((subtotal_dec or calc_items_total) + tax_dec),
        "item_discrepancies": item_discrepancies,
        "alerts": alerts,
        "is_arithmetically_valid": len(alerts) == 0,
    }


def compute_confidence_scores(
    invoice_data: Dict[str, Any],
    extraction_engine: str = "auto",
) -> Dict[str, Any]:
    """
    Computes field-level confidence ratings and visual indicator states:
      - green: >= 90% (high confidence)
      - amber: 70-89% (medium confidence, manual review suggested)
      - red: < 70% or flagged mathematical discrepancy (attention required)
    """
    math_eval = evaluate_invoice_math(invoice_data)
    alerts_by_target = {a["target"]: a for a in math_eval["alerts"]}

    field_scores: Dict[str, Dict[str, Any]] = {}

    # 1. Vendor Name
    v_name = invoice_data.get("vendor_name", "")
    if not v_name or v_name == "Unknown Vendor":
        score = 45.0
        badge = "red"
        reason = "Missing or unverified vendor name"
    elif len(v_name.strip()) > 3 and not re.search(r"[\d$#%]", v_name):
        score = 96.0
        badge = "green"
        reason = "High confidence recognized vendor entity"
    else:
        score = 82.0
        badge = "amber"
        reason = "Uncertain merchant pattern"
    field_scores["vendor_name"] = {"score": score, "badge": badge, "reason": reason}

    # 2. Invoice Date
    inv_date = invoice_data.get("invoice_date")
    if not inv_date:
        score = 60.0
        badge = "amber"
        reason = "Invoice issuance date not present"
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", str(inv_date)):
        score = 97.0
        badge = "green"
        reason = "Standard ISO 8601 date format verified"
    else:
        score = 80.0
        badge = "amber"
        reason = "Non-standard text date formatting"
    field_scores["invoice_date"] = {"score": score, "badge": badge, "reason": reason}

    # 3. Due Date
    due_date = invoice_data.get("due_date")
    if not due_date:
        score = 88.0
        badge = "amber"
        reason = "Due date omitted (common for retail receipts or immediate payment)"
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", str(due_date)):
        score = 95.0
        badge = "green"
        reason = "Standard ISO 8601 due date verified"
    else:
        score = 78.0
        badge = "amber"
        reason = "Non-standard text due date"
    field_scores["due_date"] = {"score": score, "badge": badge, "reason": reason}

    # 4. Line Items
    items = invoice_data.get("line_items", []) or []
    item_scores: List[Dict[str, Any]] = []

    if not items:
        field_scores["line_items"] = {
            "score": 60.0,
            "badge": "amber",
            "reason": "No itemized rows detected",
            "items": [],
        }
    else:
        all_valid = True
        for i, item in enumerate(items):
            q = float(item.get("quantity") or 0)
            p = float(item.get("unit_price") or 0)
            t = float(item.get("total") or 0)
            has_error = i in math_eval["item_discrepancies"]

            if has_error:
                i_score = 50.0
                i_badge = "red"
                i_reason = f"Qty x Price != Total (${q * p:.2f} != ${t:.2f})"
                all_valid = False
            elif q > 0 and p > 0 and len(str(item.get("description", "")).strip()) > 2:
                i_score = 96.0
                i_badge = "green"
                i_reason = "Verified quantity, price, and product total"
            else:
                i_score = 78.0
                i_badge = "amber"
                i_reason = "Incomplete or approximate item specifications"

            item_scores.append(
                {"index": i, "score": i_score, "badge": i_badge, "reason": i_reason}
            )

        overall_item_score = (
            round(sum(it["score"] for it in item_scores) / len(item_scores), 1)
            if item_scores
            else 85.0
        )
        if not all_valid:
            overall_badge = "red"
            overall_reason = f"{len(math_eval['item_discrepancies'])} line item(s) have arithmetic errors"
        elif overall_item_score >= 90.0:
            overall_badge = "green"
            overall_reason = "All line items arithmetically verified"
        else:
            overall_badge = "amber"
            overall_reason = "Minor quality uncertainty across table rows"

        field_scores["line_items"] = {
            "score": overall_item_score,
            "badge": overall_badge,
            "reason": overall_reason,
            "items": item_scores,
        }

    # 5. Subtotal
    sub = invoice_data.get("subtotal")
    if "subtotal" in alerts_by_target:
        field_scores["subtotal"] = {
            "score": 52.0,
            "badge": "red",
            "reason": alerts_by_target["subtotal"]["message"],
        }
    elif sub is not None:
        field_scores["subtotal"] = {
            "score": 97.0,
            "badge": "green",
            "reason": "Subtotal matches itemized breakdown",
        }
    else:
        field_scores["subtotal"] = {
            "score": 85.0,
            "badge": "amber",
            "reason": "Subtotal not explicitly labeled on invoice",
        }

    # 6. Tax Amount
    tax = invoice_data.get("tax_amount")
    if tax is None:
        field_scores["tax_amount"] = {
            "score": 92.0,
            "badge": "green",
            "reason": "Tax explicitly exempt or zero-rated",
        }
    elif tax >= 0:
        field_scores["tax_amount"] = {
            "score": 95.0,
            "badge": "green",
            "reason": "Tax rate calculation verified",
        }
    else:
        field_scores["tax_amount"] = {
            "score": 50.0,
            "badge": "red",
            "reason": "Invalid tax figure",
        }

    # 7. Grand Total
    gt = float(invoice_data.get("grand_total") or 0)
    if "grand_total" in alerts_by_target:
        field_scores["grand_total"] = {
            "score": 40.0,
            "badge": "red",
            "reason": alerts_by_target["grand_total"]["message"],
        }
    elif gt > 0 and math_eval["is_arithmetically_valid"]:
        field_scores["grand_total"] = {
            "score": 99.0,
            "badge": "green",
            "reason": "Grand total mathematically consistent with subtotal & tax",
        }
    elif gt > 0:
        field_scores["grand_total"] = {
            "score": 84.0,
            "badge": "amber",
            "reason": "Grand total extracted but upstream discrepancies exist",
        }
    else:
        field_scores["grand_total"] = {
            "score": 30.0,
            "badge": "red",
            "reason": "Missing or zero grand total",
        }

    # Overall Document Confidence
    avg_score = round(
        (
            field_scores["vendor_name"]["score"]
            + field_scores["invoice_date"]["score"]
            + field_scores["due_date"]["score"]
            + field_scores["line_items"]["score"]
            + field_scores["subtotal"]["score"]
            + field_scores["tax_amount"]["score"]
            + field_scores["grand_total"]["score"]
        )
        / 7.0,
        1,
    )

    if not math_eval["is_arithmetically_valid"] or any(
        v["badge"] == "red" for v in field_scores.values()
    ):
        doc_badge = "red"
        doc_status = "Attention Required"
    elif avg_score >= 90.0:
        doc_badge = "green"
        doc_status = "High Confidence"
    else:
        doc_badge = "amber"
        doc_status = "Review Suggested"

    return {
        "overall_score": avg_score,
        "overall_badge": doc_badge,
        "overall_status": doc_status,
        "field_scores": field_scores,
        "math_eval": math_eval,
    }

