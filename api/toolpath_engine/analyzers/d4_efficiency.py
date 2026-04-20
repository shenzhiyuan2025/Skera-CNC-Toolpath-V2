from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..models import Issue, MotionSegment, Severity


def analyze_d4(segments: List[MotionSegment], metrics: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[List[Issue], Dict[str, Any], float]:
    issues: List[Issue] = []
    d4_cfg = cfg.get("d4_rules", {})
    rapid_ratio = float(metrics.get("rapid_ratio", 0.0))
    short_ratio = float(metrics.get("short_segment_ratio", 0.0))
    feed_changes = int(metrics.get("feed_changes", 0))
    retract_ratio = float(metrics.get("retract_ratio", 0.0))

    metrics_out = {
        "rapid_ratio": rapid_ratio,
        "short_segment_ratio": short_ratio,
        "feed_changes": feed_changes,
        "retract_ratio": retract_ratio,
    }

    penalty = 0.0

    rapid_warn = float(d4_cfg.get("rapid_ratio_warn", 0.45))
    rapid_high = float(d4_cfg.get("rapid_ratio_high", 0.60))
    if rapid_ratio > rapid_high:
        issues.append(
            Issue(
                code="D4_EFF_001",
                title="空走比例过高",
                description=f"空走比例 {rapid_ratio:.1%} 超过阈值 {rapid_high:.1%}",
                severity=Severity.high,
                category="efficiency",
                dimension="D4",
                evidence={"rapid_ratio": rapid_ratio, "threshold": rapid_high},
                suggestion="优化刀路排序与分区策略，减少无效移动与回撤。",
            )
        )
        penalty += 2.0
    elif rapid_ratio > rapid_warn:
        issues.append(
            Issue(
                code="D4_EFF_002",
                title="空走比例偏高",
                description=f"空走比例 {rapid_ratio:.1%} 高于建议阈值 {rapid_warn:.1%}",
                severity=Severity.low,
                category="efficiency",
                dimension="D4",
                evidence={"rapid_ratio": rapid_ratio, "threshold": rapid_warn},
                suggestion="尝试启用最短路径排序或合并相邻加工区域，降低空走。",
            )
        )
        penalty += 0.6

    short_warn = float(d4_cfg.get("short_segment_ratio_warn", 0.25))
    short_high = float(d4_cfg.get("short_segment_ratio_high", 0.40))
    if short_ratio > short_high:
        issues.append(
            Issue(
                code="D4_EFF_003",
                title="短线段密度过高",
                description=f"短线段比例 {short_ratio:.1%} 超过阈值 {short_high:.1%}",
                severity=Severity.medium,
                category="efficiency",
                dimension="D4",
                evidence={"short_segment_ratio": short_ratio, "threshold": short_high},
                suggestion="降低离散化密度或启用样条/圆弧拟合，减少碎段。",
            )
        )
        penalty += 1.2
    elif short_ratio > short_warn:
        issues.append(
            Issue(
                code="D4_EFF_004",
                title="短线段偏多",
                description=f"短线段比例 {short_ratio:.1%} 高于建议阈值 {short_warn:.1%}",
                severity=Severity.low,
                category="efficiency",
                dimension="D4",
                evidence={"short_segment_ratio": short_ratio, "threshold": short_warn},
                suggestion="适当放宽曲线拟合公差并启用刀路平滑，提升效率。",
            )
        )
        penalty += 0.6

    feed_warn = int(d4_cfg.get("feed_change_warn", 30))
    if feed_changes > feed_warn:
        issues.append(
            Issue(
                code="D4_EFF_005",
                title="进给切换频繁",
                description=f"进给切换 {feed_changes} 次，建议阈值 {feed_warn} 次",
                severity=Severity.low,
                category="efficiency",
                dimension="D4",
                evidence={"feed_changes": feed_changes, "threshold": feed_warn},
                suggestion="按工序段统一进给策略，减少细碎 F 指令。",
            )
        )
        penalty += min(1.2, (feed_changes - feed_warn) * 0.02)

    retract_warn = float(d4_cfg.get("retract_ratio_warn", 0.10))
    if retract_ratio > retract_warn:
        issues.append(
            Issue(
                code="D4_EFF_006",
                title="抬刀/回撤偏多",
                description=f"抬刀比例 {retract_ratio:.1%} 高于建议阈值 {retract_warn:.1%}",
                severity=Severity.low,
                category="efficiency",
                dimension="D4",
                evidence={"retract_ratio": retract_ratio, "threshold": retract_warn},
                suggestion="优化分区与连刀策略，减少不必要的抬刀与回撤。",
            )
        )
        penalty += 0.6

    return issues, metrics_out, penalty

