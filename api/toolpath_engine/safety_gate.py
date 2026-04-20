from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Tuple

from .models import Issue, MachineConfig, MotionSegment, Severity


def _issue(
    code: str,
    title: str,
    description: str,
    severity: Severity,
    category: str,
    dimension: str,
    line_no: int,
    evidence: Dict[str, Any],
    suggestion: str,
) -> Issue:
    return Issue(
        code=code,
        title=title,
        description=description,
        severity=severity,
        category=category,
        dimension=dimension,
        line_range=(line_no, line_no),
        evidence=evidence,
        suggestion=suggestion,
    )


def run_safety_gate(
    machine: MachineConfig,
    segments: List[MotionSegment],
    supported_codes: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Tuple[List[Issue], Dict[str, Any]]:
    issues: List[Issue] = []
    metrics: Dict[str, Any] = {"blocker_count": 0}

    supported_g = set(int(x) for x in supported_codes.get("gcodes", []))
    supported_m = set(int(x) for x in supported_codes.get("mcodes", []))
    d1_cfg = cfg.get("d1_rules", {}) or {}
    low_z_rapid_blocker_xy_mm = float(d1_cfg.get("low_z_rapid_blocker_xy_mm", 80.0))

    for seg in segments:
        for axis, limit in machine.axis_limits.items():
            v = float(seg.end.get(axis, 0.0))
            if v < limit.minimum or v > limit.maximum:
                issues.append(
                    _issue(
                        code="SG_AXL_001",
                        title="轴超行程",
                        description=f"{axis.upper()} 轴超出行程范围：{v:.3f}，限制 [{limit.minimum}, {limit.maximum}]",
                        severity=Severity.blocker,
                        category="safety_gate",
                        dimension="D1",
                        line_no=seg.line_no,
                        evidence={"axis": axis, "value": v, "limit": [limit.minimum, limit.maximum]},
                        suggestion="检查工件零点、后处理行程限制、刀具长度/夹具安装位置；必要时重新规划姿态。",
                    )
                )

        if seg.mode == "G0":
            dz_min = min(seg.start["z"], seg.end["z"])
            xy = (seg.end["x"] - seg.start["x"]) ** 2 + (seg.end["y"] - seg.start["y"]) ** 2
            if dz_min < machine.safe_z_mm and xy ** 0.5 >= low_z_rapid_blocker_xy_mm:
                issues.append(
                    _issue(
                        code="SG_RAP_001",
                        title="危险区域快移",
                        description=f"Safe Z({machine.safe_z_mm}mm) 以下发生 G0 XY 大范围快移",
                        severity=Severity.blocker,
                        category="safety_gate",
                        dimension="D1",
                        line_no=seg.line_no,
                        evidence={"safe_z_mm": machine.safe_z_mm, "xy_move_mm": xy ** 0.5, "z_min_mm": dz_min, "blocker_xy_mm": low_z_rapid_blocker_xy_mm},
                        suggestion="大范围移动前先抬刀到 Safe Z 以上，避免跨区域穿越工件/夹具。",
                    )
                )

        max_tilt = max(abs(seg.end["a"]), abs(seg.end["b"]))
        if max_tilt > machine.max_tilt_deg:
            issues.append(
                _issue(
                    code="SG_TILT_001",
                    title="姿态不可达",
                    description=f"A/B 倾角 {max_tilt:.2f}° 超出安全包络 {machine.max_tilt_deg}°",
                    severity=Severity.blocker,
                    category="safety_gate",
                    dimension="D1",
                    line_no=seg.line_no,
                    evidence={"max_tilt_deg": max_tilt, "limit_deg": machine.max_tilt_deg},
                    suggestion="降低 A/B 轴倾角上限或改用分度加工策略；检查后处理五轴限制配置。",
                )
            )

        z_min = min(seg.start["z"], seg.end["z"])
        rotary_jump = max(abs(seg.end["a"] - seg.start["a"]), abs(seg.end["b"] - seg.start["b"]), abs(seg.end["c"] - seg.start["c"]))
        if z_min < machine.safe_z_mm and rotary_jump > machine.max_low_z_rotary_jump_deg:
            issues.append(
                _issue(
                    code="SG_ROT_001",
                    title="低高度旋转跳变过大",
                    description=f"Safe Z({machine.safe_z_mm}mm) 以下发生较大旋转轴跳变 {rotary_jump:.2f}°",
                    severity=Severity.blocker,
                    category="safety_gate",
                    dimension="D1",
                    line_no=seg.line_no,
                    evidence={"rotary_jump_deg": rotary_jump, "limit_deg": machine.max_low_z_rotary_jump_deg, "z_min_mm": z_min},
                    suggestion="在低高度区间降低旋转轴步进；或先抬刀到 Safe Z 再旋转。",
                )
            )

        for g in seg.meta.get("gcodes", []):
            if int(g) not in supported_g:
                continue
        for m in seg.meta.get("mcodes", []):
            if int(m) not in supported_m:
                continue

    metrics["blocker_count"] = sum(1 for i in issues if i.severity == Severity.blocker)
    return issues, metrics
