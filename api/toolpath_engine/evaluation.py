from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .analyzers import analyze_d1, analyze_d4, analyze_d6
from .conclusion_engine import decide_conclusion, summary_text
from .gcode_parser import parse_gcode
from .motion_builder import build_motion_segments
from .report_generator import build_artifacts
from .rule_config import load_machine_config, load_rule_config
from .safety_gate import run_safety_gate
from .scoring_engine import compute_issue_counts, score_dimensions
from .models import Conclusion, EvaluationResult, Issue


def evaluate_gcode(
    gcode_text: str,
    *,
    file_name: str = "",
    software_source: str = "",
    machine_model: str = "",
) -> EvaluationResult:
    raw_cfg = load_rule_config()
    machine_cfg = load_machine_config(raw_cfg)
    supported = raw_cfg.get("supported_codes", {}) or {}
    thresholds = raw_cfg.get("thresholds", {}) or {}
    dim_weights = raw_cfg.get("dimension_weights", {}) or {}

    blocks = parse_gcode(gcode_text)
    segments, motion_metrics = build_motion_segments(blocks)

    safety_issues, safety_metrics = run_safety_gate(machine_cfg, segments, supported, raw_cfg)
    issues: List[Issue] = []
    issues.extend(safety_issues)

    dimension_penalties: Dict[str, float] = {k: 0.0 for k in dim_weights.keys()}
    dimension_metrics: Dict[str, Any] = {}

    has_blocker = bool(safety_metrics.get("blocker_count", 0))
    if not has_blocker:
        d1_issues, d1_metrics, d1_pen = analyze_d1(machine_cfg, segments, raw_cfg)
        d4_issues, d4_metrics, d4_pen = analyze_d4(segments, motion_metrics, raw_cfg)
        d6_issues, d6_metrics, d6_pen = analyze_d6(blocks, supported, raw_cfg)

        issues.extend(d1_issues)
        issues.extend(d4_issues)
        issues.extend(d6_issues)

        dimension_penalties["D1"] = float(dimension_penalties.get("D1", 0.0)) + float(d1_pen)
        dimension_penalties["D4"] = float(dimension_penalties.get("D4", 0.0)) + float(d4_pen)
        dimension_penalties["D6"] = float(dimension_penalties.get("D6", 0.0)) + float(d6_pen)

        dimension_metrics["D1"] = d1_metrics
        dimension_metrics["D4"] = d4_metrics
        dimension_metrics["D6"] = d6_metrics

    dimension_scores = score_dimensions(dim_weights, dimension_penalties)
    if has_blocker:
        dimension_scores = {k: 0.0 for k in dim_weights.keys()}
        total_score = 0.0
    else:
        total_score = round(sum(dimension_scores.values()), 2)
    issue_counts = compute_issue_counts(issues)
    conclusion = decide_conclusion(issue_counts, total_score, dimension_scores, thresholds)
    allow_continue = conclusion != Conclusion.red

    task_meta = {
        "task_name": "toolpath-eval",
        "file_name": file_name,
        "software_source": software_source,
        "machine_model": machine_model or machine_cfg.machine_name,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = EvaluationResult(
        final_conclusion=conclusion,
        allow_continue=allow_continue,
        summary=summary_text(conclusion, issue_counts.get("blocker", 0)),
        total_score=total_score,
        dimension_scores=dimension_scores,
        issue_counts=issue_counts,
        issues=issues,
        artifacts={},
        metrics={
            **motion_metrics,
            **safety_metrics,
            "dimension_metrics": dimension_metrics,
        },
        task_meta=task_meta,
    )
    result.artifacts = build_artifacts(result)
    return result
