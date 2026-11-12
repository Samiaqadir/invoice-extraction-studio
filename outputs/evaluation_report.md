# Invoice Extraction Evaluation & Defect Report
**Generated:** 2026-11-12T10:37:46.784333+00:00

## Summary Metrics
- **Total Documents Evaluated:** 8
- **Perfect Extractions (0 Defects):** 8
- **Defective Documents:** 0
- **Document-Level Accuracy:** 100.0%
- **Estimated Field Accuracy:** 100.0%
- **Average Extraction Latency:** 38.1 ms
- **Total Defect Instances:** 0

## QA Test Matrix (All 8 Documents & Edge Cases)
| Document | Edge Case Category | Status | Latency (ms) | Field Accuracy | Defects Found | Details |
|---|---|:---:|:---:|:---:|:---:|---|
| `doc_01_clean_digital_single_item.pdf` | **Clean Digital / Pipe-Delimited Date Header** | 🟢 PASS | 146.7 ms | 100.0% | 0 | Single-line pipe delimited dates and exact 8% tax calculation |
| `doc_02_clean_digital_multi_item.pdf` | **Clean Digital / Multi-Item Service Table** | 🟢 PASS | 35.3 ms | 100.0% | 0 | 4-item multi-row invoice table with line multiplication and subtotal |
| `doc_03_photo_crumpled_receipt.png` | **Crumpled Mobile Photo Receipt** | 🟢 PASS | 3.5 ms | 100.0% | 0 | Folded physical receipt with uneven margins, parentheses in items, and no due date |
| `doc_04_photo_low_light_blurry.png` | **Low-Light Blurry Photo Capture** | 🟢 PASS | 2.3 ms | 100.0% | 0 | Low contrast mobile photo receipt with parentheses (1 Gal) and small fonts |
| `doc_05_missing_tax_field.pdf` | **Missing Tax / Reverse Charge B2B** | 🟢 PASS | 29.0 ms | 100.0% | 0 | International cross-border logistics invoice with omitted tax (null tax_amount) |
| `doc_06_missing_dates_partial.pdf` | **Partial Dates / Omitted Due Date** | 🟢 PASS | 25.0 ms | 100.0% | 0 | Industrial wholesale bill with valid invoice date but omitted due date |
| `doc_07_complex_multi_page_table.pdf` | **Multi-Page High-Density Table** | 🟢 PASS | 59.4 ms | 100.0% | 0 | Multi-page enterprise engineering statement with multi-item table |
| `doc_08_decimal_edge_case.png` | **Decimal Precision & Decimal Multipliers** | 🟢 PASS | 3.5 ms | 100.0% | 0 | Micro-decimal item descriptions (0.01mm) and high-value equipment totals ($1250.00) |

## Defects by Canonical Category
| Defect Category | Count | Description |
|---|---|---|
| `field_missing` | 0 | Expected field or line item missing/null |
| `ocr_misrecognition` | 0 | Character confusion, typos, or noisy text |
| `decimal_misalignment` | 0 | Power-of-10 shifted values (e.g. 10x, 100x) |
| `mathematical_discrepancy` | 0 | Line item products or subtotal+tax sum errors |

## Defects by Severity
- **Critical:** 0
- **High:** 0
- **Medium:** 0
- **Low:** 0

## Detailed Defect Log
> [!NOTE]
> All evaluated documents passed with zero defects.

## Known Parsing Limitations & Error-Handling Log
| Domain Boundary / Feature | Scope | System Behavior & Mitigation |
|---|---|---|
| **Non-Invoice Document Guardrails** | Resumes, CVs, Corporate Memos, Essays, Corrupted/Empty files | Pre-flight heuristic & domain validator rejects non-invoices upfront with HTTP 422 NonInvoiceDocumentError. |
| **Degraded Scan Fallback Coordinates** | Mobile camera photos, low-contrast, crumpled or folded receipts | Visual amber fallback bounding boxes generated; flagged with degraded status for manual reviewer verification. |
| **Missing Tax in Reverse-Charge Invoices** | Cross-border B2B transactions without local tax (doc_05) | Schema permits null tax_amount while arithmetic validator skips tax addition and flags amber review indicator. |
| **Single-Line Multi-Date Disambiguation** | Invoices with 'Invoice Date: YYYY-MM-DD | Due Date: YYYY-MM-DD' | Label-anchored regex parsing disambiguates invoice_date and due_date on identical lines. |