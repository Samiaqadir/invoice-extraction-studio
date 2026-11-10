# Invoice Extraction Evaluation & Defect Report
**Generated:** 2026-11-10T10:52:29.246651+00:00

## Summary Metrics
- **Total Documents Evaluated:** 8
- **Perfect Extractions (0 Defects):** 2
- **Defective Documents:** 6
- **Document-Level Accuracy:** 25.0%
- **Estimated Field Accuracy:** 81.25%
- **Total Defect Instances:** 15

## Defects by Canonical Category
| Defect Category | Count | Description |
|---|---|---|
| `field_missing` | 2 | Expected field or line item missing/null |
| `ocr_misrecognition` | 11 | Character confusion, typos, or noisy text |
| `decimal_misalignment` | 0 | Power-of-10 shifted values (e.g. 10x, 100x) |
| `mathematical_discrepancy` | 2 | Line item products or subtotal+tax sum errors |

## Defects by Severity
- **Critical:** 0
- **High:** 4
- **Medium:** 11
- **Low:** 0

## Detailed Defect Log
| ID | Document | Category | Path | Expected | Actual | Severity | Diagnostic |
|---|---|---|---|---|---|---|---|
| `DEF-C4727DD2` | `doc_01_clean_digital_single_item.pdf` | `ocr_misrecognition` | `due_date` | `2026-10-31` | `2026-10-01` | **medium** | Text OCR misrecognition on 'due_date' (similarity: 90.00%): expected '2026-10-31', got '2026-10-01' |
| `DEF-42B9EC10` | `doc_02_clean_digital_multi_item.pdf` | `ocr_misrecognition` | `due_date` | `2026-11-15` | `2026-10-15` | **medium** | Text OCR misrecognition on 'due_date' (similarity: 90.00%): expected '2026-11-15', got '2026-10-15' |
| `DEF-1402FBBA` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[0].description` | `Artisan Latte (Large)` | `Avocado Sourdough Toast` | **medium** | Line item #1 description OCR noise (22.73%): 'Avocado Sourdough Toast' != 'Artisan Latte (Large)' |
| `DEF-757DD832` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[0].quantity` | `2.0` | `1.0` | **medium** | Line item #1 quantity mismatch: expected 2.0, got 1.0 |
| `DEF-2274F531` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[0].unit_price` | `5.5` | `13.0` | **medium** | Line item #1 unit_price mismatch: expected 5.5, got 13.0 |
| `DEF-857EB258` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[0].total` | `11.0` | `13.0` | **medium** | Line item #1 total mismatch: expected 11.0, got 13.0 |
| `DEF-8552B72A` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[1].description` | `Avocado Sourdough Toast` | `Almond Croissant` | **medium** | Line item #2 description OCR noise (25.64%): 'Almond Croissant' != 'Avocado Sourdough Toast' |
| `DEF-351E50EE` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[1].unit_price` | `13.0` | `4.5` | **medium** | Line item #2 unit_price mismatch: expected 13.0, got 4.5 |
| `DEF-4AF48833` | `doc_03_photo_crumpled_receipt.png` | `ocr_misrecognition` | `line_items[1].total` | `13.0` | `4.5` | **medium** | Line item #2 total mismatch: expected 13.0, got 4.5 |
| `DEF-4682FE4F` | `doc_03_photo_crumpled_receipt.png` | `field_missing` | `line_items[2]` | `{'description': 'Almond Croissant', 'quantity': 1.0, 'total': 4.5, 'unit_price': 4.5}` | `None` | **high** | Missing line item #3: 'Almond Croissant' |
| `DEF-4F0CF66D` | `doc_03_photo_crumpled_receipt.png` | `mathematical_discrepancy` | `subtotal` | `17.5` | `28.5` | **high** | Line items total sum (17.5) does not equal subtotal (28.5) [diff: 11.00] |
| `DEF-8E0D0D60` | `doc_04_photo_low_light_blurry.png` | `field_missing` | `line_items[1]` | `{'description': 'Windshield Fluid (1 Gal)', 'quantity': 2.0, 'total': 9.0, 'unit_price': 4.5}` | `None` | **high** | Missing line item #2: 'Windshield Fluid (1 Gal)' |
| `DEF-28D18C4B` | `doc_04_photo_low_light_blurry.png` | `mathematical_discrepancy` | `subtotal` | `38.0` | `47.0` | **high** | Line items total sum (38.0) does not equal subtotal (47.0) [diff: 9.00] |
| `DEF-D82EC994` | `doc_05_missing_tax_field.pdf` | `ocr_misrecognition` | `due_date` | `2026-11-22` | `2026-10-22` | **medium** | Text OCR misrecognition on 'due_date' (similarity: 90.00%): expected '2026-11-22', got '2026-10-22' |
| `DEF-FE0C0A16` | `doc_07_complex_multi_page_table.pdf` | `ocr_misrecognition` | `due_date` | `2026-11-28` | `2026-10-28` | **medium** | Text OCR misrecognition on 'due_date' (similarity: 90.00%): expected '2026-11-28', got '2026-10-28' |