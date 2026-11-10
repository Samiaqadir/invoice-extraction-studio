# Invoice Extraction Studio — Test Pack Dataset

This directory contains the canonical benchmark test dataset for validating invoice extraction pipelines. The test pack is intentionally curated to evaluate model accuracy across clean digital files, real-world smartphone photos, multi-item tabular layouts, and partial/edge-case schemas.

---

## Benchmark Document Catalog (8 Distinct Documents)

| Document Filename | Format | Complexity Category | Core Challenge / Evaluation Focus |
|---|---|---|---|
| `doc_01_clean_digital_single_item.pdf` | Vector PDF | **Clean Digital Single-Item** | High-fidelity digital PDF, single subscription line item, baseline extraction benchmark. |
| `doc_02_clean_digital_multi_item.pdf` | Vector PDF | **Multi-Item Tabular Layout** | 4 itemized line items across cloud services, tabular grid parsing, subtotal and tax sum validation. |
| `doc_03_photo_crumpled_receipt.png` | Photo PNG | **Smartphone Photo Receipt** | Folded/crumpled receipt, perspective distortion, non-standard retail POS layout, null due date. |
| `doc_04_photo_low_light_blurry.png` | Photo PNG | **Smartphone Photo (Degraded)** | Low-light ambient noise, motion blur, thermal paper print fade, retail item table. |
| `doc_05_missing_tax_field.pdf` | Vector PDF | **Missing Tax Field (0% / Exempt)** | Cross-border logistics invoice where tax is explicitly absent/null (`subtotal == grand_total`). |
| `doc_06_missing_dates_partial.pdf` | Vector PDF | **Missing Date Metadata** | Incomplete invoice document omitting invoice issuance and payment due dates (`null`). |
| `doc_07_complex_multi_page_table.pdf` | Vector PDF | **Multi-Page Enterprise Table** | Dense multi-item catalog (7 items) with multi-row descriptions, unit rates, and discount tiers. |
| `doc_08_decimal_edge_case.png` | Image PNG | **Decimal Precision Edge Case** | Cents fraction rounding, multi-digit amounts, testing decimal point alignment vs shift errors. |

---

## File Placement & Structure

Place document files directly in `test_pack/` using the canonical naming pattern:

```text
test_pack/
├── README.md                               # This specification document
├── ground_truth.json                       # Master benchmark expectations
├── doc_01_clean_digital_single_item.pdf     # Primary test artifact
├── doc_01_clean_digital_single_item.txt     # Optional OCR text representation
├── doc_02_clean_digital_multi_item.pdf
├── doc_02_clean_digital_multi_item.txt
├── doc_03_photo_crumpled_receipt.png
├── doc_03_photo_crumpled_receipt.txt
├── doc_04_photo_low_light_blurry.png
├── doc_04_photo_low_light_blurry.txt
├── doc_05_missing_tax_field.pdf
├── doc_05_missing_tax_field.txt
├── doc_06_missing_dates_partial.pdf
├── doc_06_missing_dates_partial.txt
├── doc_07_complex_multi_page_table.pdf
├── doc_07_complex_multi_page_table.txt
├── doc_08_decimal_edge_case.png
└── doc_08_decimal_edge_case.txt
```

---

## Ground Truth Schema (`ground_truth.json`)

Each document in `ground_truth.json` is keyed by its filename:

```json
{
  "doc_01_clean_digital_single_item.pdf": {
    "vendor_name": "Nexus Software Inc",
    "invoice_date": "2026-10-01",
    "due_date": "2026-10-31",
    "line_items": [
      {
        "description": "Annual Developer SaaS Subscription",
        "quantity": 1.0,
        "unit_price": 1200.0,
        "total": 1200.0
      }
    ],
    "subtotal": 1200.0,
    "tax_amount": 96.0,
    "grand_total": 1296.0
  }
}
```

### Adding New Test Documents

1. Save the document into `test_pack/` with an informative prefix (e.g., `doc_09_handwritten_invoice.png`).
2. Add its validated reference extraction entry to `test_pack/ground_truth.json`.
3. Optionally add a `.txt` text sidecar file for local OCR fallback environments.
4. Run the benchmark suite:
   ```bash
   python -m evals.evaluate_test_pack
   ```

