from __future__ import annotations

from typing import Dict

from .models import Conclusion


def decide_conclusion(
    issue_counts: Dict[str, int],
    total_score: float,
    dimension_scores: Dict[str, float],
    thresholds: Dict[str, object],
) -> Conclusion:
    if issue_counts.get("blocker", 0) > 0:
        return Conclusion.red

    yellow_total = float(thresholds.get("yellow_total_score_lt", 80.0))
    yellow_high = int(thresholds.get("yellow_high_issue_gte", 1))
    yellow_medium = int(thresholds.get("yellow_medium_issue_gte", 3))
    critical_floor = thresholds.get("critical_dimension_floor", {}) or {}

    if total_score < yellow_total:
        return Conclusion.yellow
    if issue_counts.get("high", 0) >= yellow_high:
        return Conclusion.yellow
    if issue_counts.get("medium", 0) >= yellow_medium:
        return Conclusion.yellow

    for dim, floor in critical_floor.items():
        if float(dimension_scores.get(dim, 0.0)) < float(floor):
            return Conclusion.yellow

    return Conclusion.green


def summary_text(conclusion: Conclusion, blocker_count: int) -> str:
    if conclusion == Conclusion.red:
        return f"存在关键安全问题（Blocker {blocker_count} 项），需处理后继续。"
    if conclusion == Conclusion.yellow:
        return "存在注意事项，建议确认后继续。"
    return "通过检查，可继续加工。"

