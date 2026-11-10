"""
Evaluation and Defect Tracking Package
======================================
Defines structured defect logging and benchmarking tools for invoice extraction.
"""

from evals.defect_tracker import (
    DefectRecord,
    DefectSeverity,
    DefectTracker,
    DefectType,
    EvaluationSummary,
)

__all__ = [
    "DefectRecord",
    "DefectSeverity",
    "DefectTracker",
    "DefectType",
    "EvaluationSummary",
]

