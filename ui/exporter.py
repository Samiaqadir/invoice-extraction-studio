"""
Invoice Export Module (JSON & CSV)
==================================
Transforms validated invoice data into standardized JSON and CSV formats
for downstream ERP ingestion, accounting software, and compliance auditing.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Union

from schema.invoice_schema import Invoice


def invoice_to_csv_string(invoice_data: Dict[str, Any]) -> str:
    """
    Converts invoice dictionary into standardized CSV representation with
    denormalized line items and master header metadata.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    headers = [
        "vendor_name",
        "invoice_date",
        "due_date",
        "line_item_index",
        "item_description",
        "quantity",
        "unit_price",
        "item_total",
        "subtotal",
        "tax_amount",
        "grand_total",
    ]
    writer.writerow(headers)

    v_name = invoice_data.get("vendor_name", "")
    inv_date = invoice_data.get("invoice_date", "") or ""
    due_date = invoice_data.get("due_date", "") or ""
    subtotal = invoice_data.get("subtotal", "")
    tax_amount = invoice_data.get("tax_amount", "")
    grand_total = invoice_data.get("grand_total", 0.0)

    line_items = invoice_data.get("line_items", []) or []

    if not line_items:
        writer.writerow(
            [
                v_name,
                inv_date,
                due_date,
                1,
                "",
                0.0,
                0.0,
                0.0,
                subtotal if subtotal is not None else "",
                tax_amount if tax_amount is not None else "",
                grand_total,
            ]
        )
    else:
        for idx, item in enumerate(line_items, start=1):
            writer.writerow(
                [
                    v_name,
                    inv_date,
                    due_date,
                    idx,
                    item.get("description", ""),
                    item.get("quantity", 0.0),
                    item.get("unit_price", 0.0),
                    item.get("total", 0.0),
                    subtotal if subtotal is not None else "",
                    tax_amount if tax_amount is not None else "",
                    grand_total,
                ]
            )

    return output.getvalue()


def export_invoice_files(
    invoice_data: Dict[str, Any],
    doc_id: str,
    output_dir: Union[str, Path] = "outputs",
) -> Dict[str, Path]:
    """
    Exports reviewed and validated invoice data to disk as both JSON and CSV.
    """
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    clean_id = Path(doc_id).stem.replace(" ", "_")

    # 1. Deterministic JSON
    json_path = target_dir / f"{clean_id}_reviewed.json"
    validated_model = Invoice.model_validate(
        invoice_data, context={"strict_math": False}
    )
    json_path.write_text(
        validated_model.to_deterministic_json(indent=2), encoding="utf-8"
    )

    # 2. Standardized CSV
    csv_path = target_dir / f"{clean_id}_reviewed.csv"
    csv_content = invoice_to_csv_string(invoice_data)
    csv_path.write_text(csv_content, encoding="utf-8")

    return {
        "json": json_path,
        "csv": csv_path,
    }

