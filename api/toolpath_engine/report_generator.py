from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any, Dict, List

from .models import EvaluationResult, Issue


def issues_to_json(issues: List[Issue]) -> str:
    def to_dict(it: Issue) -> Dict[str, Any]:
        return {
            "code": it.code,
            "title": it.title,
            "description": it.description,
            "severity": it.severity.value,
            "category": it.category,
            "dimension": it.dimension,
            "line_range": list(it.line_range) if it.line_range else None,
            "segment_range": list(it.segment_range) if it.segment_range else None,
            "evidence": it.evidence,
            "suggestion": it.suggestion,
        }

    return json.dumps([to_dict(i) for i in issues], ensure_ascii=False, indent=2)


def metrics_to_csv(metrics: Dict[str, Any]) -> str:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["key", "value"])
    for k in sorted(metrics.keys()):
        writer.writerow([k, json.dumps(metrics[k], ensure_ascii=False) if isinstance(metrics[k], (dict, list)) else metrics[k]])
    return buf.getvalue()


def summary_to_markdown(result: EvaluationResult) -> str:
    lines = []
    lines.append(f"# 刀路测评结果\n")
    lines.append(f"- 结论: {result.final_conclusion.value}")
    lines.append(f"- 是否允许继续: {str(result.allow_continue).lower()}")
    lines.append(f"- 总分: {result.total_score:.2f}")
    lines.append(f"- 摘要: {result.summary}\n")
    lines.append("## 维度得分")
    for dim, score in sorted(result.dimension_scores.items()):
        lines.append(f"- {dim}: {score:.2f}")
    lines.append("\n## 问题统计")
    for k in ["blocker", "high", "medium", "low"]:
        lines.append(f"- {k}: {int(result.issue_counts.get(k, 0))}")
    return "\n".join(lines) + "\n"


def build_artifacts(result: EvaluationResult) -> Dict[str, str]:
    summary_json = json.dumps(
        {
            "final_conclusion": result.final_conclusion.value,
            "allow_continue": result.allow_continue,
            "summary": result.summary,
            "total_score": result.total_score,
            "dimension_scores": result.dimension_scores,
            "issue_counts": result.issue_counts,
            "task_meta": result.task_meta,
        },
        ensure_ascii=False,
        indent=2,
    )
    return {
        "summary_json": summary_json,
        "issues_json": issues_to_json(result.issues),
        "metrics_csv": metrics_to_csv(result.metrics),
        "summary_md": summary_to_markdown(result),
    }

