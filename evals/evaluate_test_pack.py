"""
Benchmark Evaluation Runner
===========================
Executes the evaluation suite across all documents in test_pack/ using the
extractor and logs defects into outputs/defect_summary.json and
outputs/evaluation_report.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import time
from evals.defect_tracker import DefectTracker
from pipeline.extractor import extract_invoice

logger = logging.getLogger("evals.benchmark")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_PACK_DIR = ROOT_DIR / "test_pack"
OUTPUTS_DIR = ROOT_DIR / "outputs"

DOC_EDGE_CATEGORIES = {
    "doc_01_clean_digital_single_item.pdf": (
        "Clean Digital / Pipe-Delimited Date Header",
        "Single-line pipe delimited dates and exact 8% tax calculation",
    ),
    "doc_02_clean_digital_multi_item.pdf": (
        "Clean Digital / Multi-Item Service Table",
        "4-item multi-row invoice table with line multiplication and subtotal",
    ),
    "doc_03_photo_crumpled_receipt.png": (
        "Crumpled Mobile Photo Receipt",
        "Folded physical receipt with uneven margins, parentheses in items, and no due date",
    ),
    "doc_04_photo_low_light_blurry.png": (
        "Low-Light Blurry Photo Capture",
        "Low contrast mobile photo receipt with parentheses (1 Gal) and small fonts",
    ),
    "doc_05_missing_tax_field.pdf": (
        "Missing Tax / Reverse Charge B2B",
        "International cross-border logistics invoice with omitted tax (null tax_amount)",
    ),
    "doc_06_missing_dates_partial.pdf": (
        "Partial Dates / Omitted Due Date",
        "Industrial wholesale bill with valid invoice date but omitted due date",
    ),
    "doc_07_complex_multi_page_table.pdf": (
        "Multi-Page High-Density Table",
        "Multi-page enterprise engineering statement with multi-item table",
    ),
    "doc_08_decimal_edge_case.png": (
        "Decimal Precision & Decimal Multipliers",
        "Micro-decimal item descriptions (0.01mm) and high-value equipment totals ($1250.00)",
    ),
}


def run_benchmark(engine: str = "auto") -> None:
    """Executes the test pack benchmark evaluation suite."""
    gt_path = TEST_PACK_DIR / "ground_truth.json"
    if not gt_path.exists():
        raise FileNotFoundError(f"Ground truth file not found at: {gt_path}")

    ground_truth_data = json.loads(gt_path.read_text(encoding="utf-8"))
    tracker = DefectTracker()

    logger.info(
        "Starting benchmark evaluation across %d test documents...",
        len(ground_truth_data),
    )

    for doc_name, expected_gt in ground_truth_data.items():
        doc_path = TEST_PACK_DIR / doc_name
        if not doc_path.exists():
            logger.warning("Test document '%s' does not exist on disk, skipping.", doc_name)
            continue

        cat_info = DOC_EDGE_CATEGORIES.get(
            doc_name, ("Standard Document", "Standard financial invoice format")
        )

        logger.info("Evaluating '%s' (%s)...", doc_name, cat_info[0])
        predicted = None
        start_t = time.perf_counter()
        try:
            predicted = extract_invoice(
                document_path=doc_path,
                engine=engine,
                save_output=True,
                strict_math=False,
                output_dir=OUTPUTS_DIR,
            )
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            tracker.evaluate_document(
                document_id=doc_name,
                predicted=predicted,
                ground_truth=expected_gt,
                latency_ms=elapsed_ms,
                category=cat_info[0],
                details=cat_info[1],
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            logger.error("Extraction error for '%s': %s", doc_name, e)
            tracker.evaluate_document(
                document_id=doc_name,
                predicted=None,
                ground_truth=expected_gt,
                latency_ms=elapsed_ms,
                category=cat_info[0],
                details=f"Extraction failure: {e}",
            )

    report_md_path = OUTPUTS_DIR / "evaluation_report.md"
    tracker.export_report(report_md_path)

    summary_json_path = OUTPUTS_DIR / "defect_summary.json"
    summary = tracker.get_summary()
    summary_json_path.write_text(
        summary.model_dump_json(indent=2), encoding="utf-8"
    )

    logger.info("================ BENCHMARK RESULTS ================")
    logger.info("Total Documents:    %d", summary.total_documents)
    logger.info("Perfect Documents:  %d", summary.perfect_documents)
    logger.info("Defective Docs:     %d", summary.defective_documents)
    logger.info("Document Accuracy:  %.1f%%", summary.document_accuracy_rate)
    logger.info("Field Accuracy:     %.1f%%", summary.field_accuracy_rate)
    logger.info("Defects by Type:    %s", summary.defects_by_type)
    logger.info("Evaluation report saved to: %s", report_md_path)


if __name__ == "__main__":
    import sys

    selected_engine = sys.argv[1] if len(sys.argv) > 1 else "local_ocr"
    run_benchmark(engine=selected_engine)

