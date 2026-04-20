from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import DimensionScore, Issue, Severity


def _severity_count(issues: List[Issue]) -> Dict[str, int]:
    counts = {"blocker": 0, "high": 0, "medium": 0, "low": 0}
    for it in issues:
        if it.severity.value in counts:
            counts[it.severity.value] += 1
    return counts


def score_dimensions(
    dimension_weights: Dict[str, float],
    dimension_penalties: Dict[str, float],
) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for dim, w in dimension_weights.items():
        p = float(dimension_penalties.get(dim, 0.0))
        scores[dim] = max(0.0, round(float(w) - p, 2))
    return scores


def compute_issue_counts(issues: List[Issue]) -> Dict[str, int]:
    return _severity_count(issues)

