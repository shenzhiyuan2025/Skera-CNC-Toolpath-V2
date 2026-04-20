from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..models import Issue, MachineConfig, MotionSegment, Severity


def analyze_d1(machine: MachineConfig, segments: List[MotionSegment], cfg: Dict[str, Any]) -> Tuple[List[Issue], Dict[str, Any], float]:
    issues: List[Issue] = []
    penalty = 0.0

    near_limit_hits = 0
    tilt_near_hits = 0
    low_z_rapid_count = 0
    low_z_rapid_local_count = 0

    margin_mm = 2.0
    tilt_margin_deg = 5.0
    d1_cfg = cfg.get("d1_rules", {}) or {}
    warn_xy = float(d1_cfg.get("low_z_rapid_warn_xy_mm", 5.0))
    high_xy = float(d1_cfg.get("low_z_rapid_high_xy_mm", 30.0))
    depth_tol = float(d1_cfg.get("local_reposition_depth_tol_mm", 0.8))

    severity_penalties = cfg.get("severity_penalties", {}) or {}
    p_high = float(severity_penalties.get("high", 3.0))
    p_medium = float(severity_penalties.get("medium", 1.5))
    p_low = float(severity_penalties.get("low", 0.6))

    for idx, seg in enumerate(segments):
        for axis, limit in machine.axis_limits.items():
            v = float(seg.end.get(axis, 0.0))
            if (limit.maximum - margin_mm) < v <= limit.maximum or limit.minimum <= v < (limit.minimum + margin_mm):
                near_limit_hits += 1
                break

        max_tilt = max(abs(seg.end["a"]), abs(seg.end["b"]))
        if machine.max_tilt_deg - tilt_margin_deg < max_tilt <= machine.max_tilt_deg:
            tilt_near_hits += 1

        if seg.mode == "G0":
            z_min = min(seg.start["z"], seg.end["z"])
            if z_min < machine.safe_z_mm:
                xy_move = ((seg.end["x"] - seg.start["x"]) ** 2 + (seg.end["y"] - seg.start["y"]) ** 2) ** 0.5
                if xy_move >= warn_xy:
                    low_z_rapid_count += 1
                    prev_seg = segments[idx - 1] if idx - 1 >= 0 else None
                    next_seg = segments[idx + 1] if idx + 1 < len(segments) else None
                    prev_cut = prev_seg is not None and prev_seg.mode != "G0" and min(prev_seg.start["z"], prev_seg.end["z"]) < machine.safe_z_mm
                    next_cut = next_seg is not None and next_seg.mode != "G0" and min(next_seg.start["z"], next_seg.end["z"]) < machine.safe_z_mm
                    depth_like_prev = prev_seg is not None and abs(prev_seg.end["z"] - seg.start["z"]) <= depth_tol
                    depth_like_next = next_seg is not None and abs(next_seg.start["z"] - seg.end["z"]) <= depth_tol
                    is_local = bool(prev_cut and next_cut and depth_like_prev and depth_like_next)
                    if is_local:
                        low_z_rapid_local_count += 1
                    sev = Severity.medium if is_local else Severity.high if xy_move >= high_xy else Severity.medium
                    issues.append(
                        Issue(
                            code="D1_RAP_001",
                            title="Safe Z 以下快移",
                            description="Safe Z 以下发生 G0 XY 快移，需结合上下文确认是否存在穿越风险",
                            severity=sev,
                            category="safety",
                            dimension="D1",
                            line_range=(seg.line_no, seg.line_no),
                            evidence={
                                "safe_z_mm": machine.safe_z_mm,
                                "xy_move_mm": xy_move,
                                "z_min_mm": z_min,
                                "is_local_reposition": is_local,
                                "prev_line": prev_seg.line_no if prev_seg else None,
                                "next_line": next_seg.line_no if next_seg else None,
                            },
                            suggestion="若为跨区域移动，建议先抬刀到 Safe Z；若为局部换位，确认夹具/工件无干涉并控制路径。",
                        )
                    )
                    if sev == Severity.high:
                        penalty += p_high
                    elif sev == Severity.medium:
                        penalty += p_medium
                    else:
                        penalty += p_low

    metrics_out = {
        "near_limit_hits": near_limit_hits,
        "tilt_near_hits": tilt_near_hits,
        "low_z_rapid_count": low_z_rapid_count,
        "low_z_rapid_local_count": low_z_rapid_local_count,
    }

    if near_limit_hits > 0:
        issues.append(
            Issue(
                code="D1_SAF_001",
                title="接近行程边界",
                description=f"发现 {near_limit_hits} 处运动接近轴行程边界（±{margin_mm}mm）",
                severity=Severity.medium if near_limit_hits > 5 else Severity.low,
                category="safety",
                dimension="D1",
                evidence={"hits": near_limit_hits, "margin_mm": margin_mm},
                suggestion="检查工件零点与后处理行程余量；避免在边界附近高速运行。",
            )
        )
        penalty += 1.2 if near_limit_hits > 5 else 0.6

    if tilt_near_hits > 0:
        issues.append(
            Issue(
                code="D1_SAF_002",
                title="接近姿态上限",
                description=f"发现 {tilt_near_hits} 处姿态接近倾角上限（±{tilt_margin_deg}°）",
                severity=Severity.low,
                category="safety",
                dimension="D1",
                evidence={"hits": tilt_near_hits, "tilt_margin_deg": tilt_margin_deg, "limit_deg": machine.max_tilt_deg},
                suggestion="若机床刚性或夹具空间有限，建议降低倾角并调整工艺策略。",
            )
        )
        penalty += 0.6

    return issues, metrics_out, penalty
