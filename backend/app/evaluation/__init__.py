"""
AsliOffer Evaluation and Demo Readiness Package (Task 13).
"""

import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent.parent
_repo_root = _backend_dir.parent
for _p in [str(_backend_dir), str(_repo_root)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.evaluation.corpus import EvaluationCase, load_evaluation_corpus
from app.evaluation.invariants import run_all_invariants
from app.evaluation.metrics import compute_evaluation_metrics, EvaluationMetricsReport
from app.evaluation.runner import run_evaluation, evaluate_single_case

__all__ = [
    "EvaluationCase",
    "load_evaluation_corpus",
    "run_all_invariants",
    "compute_evaluation_metrics",
    "EvaluationMetricsReport",
    "run_evaluation",
    "evaluate_single_case",
]
