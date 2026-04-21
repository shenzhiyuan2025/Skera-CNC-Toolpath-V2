from __future__ import annotations

import io
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, TextIO, Tuple

from .conclusion_engine import decide_conclusion, summary_text
from .report_generator import build_artifacts
from .rule_config import load_machine_config, load_rule_config
from .scoring_engine import compute_issue_counts, score_dimensions
from .models import Conclusion, EvaluationResult, Issue, Severity


ProgressCallback = Callable[[Dict[str, Any]], None]


def _clean_line_fast(line: str) -> str:
    if ";" in line:
        line = line.split(";", 1)[0]
    if "(" not in line:
        return line.strip().upper()
    out: List[str] = []
    depth = 0
    for ch in line:
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip().upper()


def _parse_words(cleaned: str) -> Tuple[Dict[str, float], List[int], List[int]]:
    words: Dict[str, float] = {}
    gcodes: List[int] = []
    mcodes: List[int] = []

    i = 0
    n = len(cleaned)
    while i < n:
        c = cleaned[i]
        if not ("A" <= c <= "Z"):
            i += 1
            continue
        letter = c
        i += 1
        while i < n and cleaned[i] == " ":
            i += 1
        if i >= n:
            break
        sign = 1.0
        if cleaned[i] == "+":
            i += 1
        elif cleaned[i] == "-":
            sign = -1.0
            i += 1
        start = i
        has_digit = False
        while i < n and cleaned[i].isdigit():
            i += 1
            has_digit = True
        if i < n and cleaned[i] == ".":
            i += 1
            while i < n and cleaned[i].isdigit():
                i += 1
                has_digit = True
        if not has_digit:
            continue
        try:
            value = float(cleaned[start:i]) * sign
        except ValueError:
            continue
        words[letter] = value
        if letter == "G":
            gcodes.append(int(value))
        elif letter == "M":
            mcodes.append(int(value))
    return words, gcodes, mcodes


def _iter_text_lines(text: str) -> Iterator[str]:
    for line in text.splitlines():
        yield line


def _open_text_stream(fileobj: io.BufferedIOBase) -> TextIO:
    fileobj.seek(0)
    head = fileobj.read(4)
    fileobj.seek(0)
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        encoding = "utf-16"
    elif head.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    return io.TextIOWrapper(fileobj, encoding=encoding, errors="ignore", newline="")


def evaluate_lines(
    lines: Iterable[str],
    *,
    file_name: str = "",
    software_source: str = "",
    machine_model: str = "",
    raw_cfg: Optional[Dict[str, Any]] = None,
    max_lines: Optional[int] = None,
    on_progress: Optional[ProgressCallback] = None,
    progress_every: int = 500,
) -> EvaluationResult:
    cfg = raw_cfg or load_rule_config()
    machine_cfg = load_machine_config(cfg)
    supported = cfg.get("supported_codes", {}) or {}
    thresholds = cfg.get("thresholds", {}) or {}
    dim_weights = cfg.get("dimension_weights", {}) or {}
    severity_penalties = cfg.get("severity_penalties", {}) or {}
    d1_cfg = cfg.get("d1_rules", {}) or {}
    d4_cfg = cfg.get("d4_rules", {}) or {}
    d6_cfg = cfg.get("d6_rules", {}) or {}

    limits = cfg.get("analysis_limits", {}) or {}
    max_issues = int(limits.get("max_issues", 2000))
    max_runtime_ms = int(limits.get("max_runtime_ms", 55000))
    stop_on_blocker = bool(limits.get("stop_on_first_blocker", True))
    max_blocker_issues = int(limits.get("max_blocker_issues", 10))

    start_t = time.monotonic()
    supported_g = set(int(x) for x in supported.get("gcodes", []))
    supported_m = set(int(x) for x in supported.get("mcodes", []))

    safe_z = float(machine_cfg.safe_z_mm)
    low_z_blocker_xy = float(d1_cfg.get("low_z_rapid_blocker_xy_mm", 80.0))
    low_z_warn_xy = float(d1_cfg.get("low_z_rapid_warn_xy_mm", 5.0))
    low_z_high_xy = float(d1_cfg.get("low_z_rapid_high_xy_mm", 30.0))
    depth_tol = float(d1_cfg.get("local_reposition_depth_tol_mm", 0.8))

    d4_rapid_warn = float(d4_cfg.get("rapid_ratio_warn", 0.45))
    d4_rapid_high = float(d4_cfg.get("rapid_ratio_high", 0.60))
    d4_short_warn = float(d4_cfg.get("short_segment_ratio_warn", 0.25))
    d4_short_high = float(d4_cfg.get("short_segment_ratio_high", 0.40))
    d4_feed_warn = int(d4_cfg.get("feed_change_warn", 30))
    d4_retract_warn = float(d4_cfg.get("retract_ratio_warn", 0.10))

    max_check_lines = int(d6_cfg.get("missing_modal_decl_check_lines", 30))
    max_line_len_warn = int(d6_cfg.get("max_line_len_warn", 120))

    p_high = float(severity_penalties.get("high", 3.0))
    p_medium = float(severity_penalties.get("medium", 1.5))
    p_low = float(severity_penalties.get("low", 0.6))

    issues: List[Issue] = []

    modal_absolute = True
    modal_feed = 1200.0
    modal_plane = "G17"
    motion_mode = "G0"

    x = y = z = a = b = c = 0.0
    last_feed = modal_feed

    total_lines = 0
    motion_segments = 0
    rapid_distance = 0.0
    cut_distance = 0.0
    total_distance = 0.0
    short_segments = 0
    feed_changes = 0
    retract_count = 0

    blocker_count = 0
    sampling_truncated = False

    need_units = True
    need_abs = True
    need_plane = True
    unsupported_g_hits: List[Tuple[int, int]] = []
    unsupported_m_hits: List[Tuple[int, int]] = []
    long_lines: List[int] = []

    near_limit_hits = 0
    tilt_near_hits = 0

    pending_low_z_rapid: Optional[Dict[str, Any]] = None
    prev_cut_low = False
    prev_end_z = z
    prev_line_no = 0

    def _append_issue(issue: Issue) -> None:
        nonlocal blocker_count
        if len(issues) >= max_issues:
            return
        issues.append(issue)
        if issue.severity == Severity.blocker:
            blocker_count += 1

    def _check_time() -> None:
        if (time.monotonic() - start_t) * 1000.0 > max_runtime_ms:
            raise TimeoutError("evaluation_timeout")

    def _axis_limit_blocker(line_no: int, axis: str, value: float) -> None:
        limit = machine_cfg.axis_limits[axis]
        if value < limit.minimum or value > limit.maximum:
            _append_issue(
                Issue(
                    code="SG_AXL_001",
                    title="轴超行程",
                    description=f"{axis.upper()} 轴超出行程范围：{value:.3f}，限制 [{limit.minimum}, {limit.maximum}]",
                    severity=Severity.blocker,
                    category="safety_gate",
                    dimension="D1",
                    line_range=(line_no, line_no),
                    evidence={"axis": axis, "value": value, "limit": [limit.minimum, limit.maximum]},
                    suggestion="检查工件零点、后处理行程限制、刀具长度/夹具安装位置；必要时重新规划姿态。",
                )
            )

    def _tilt_blocker(line_no: int, aa: float, bb: float) -> None:
        max_tilt = max(abs(aa), abs(bb))
        if max_tilt > machine_cfg.max_tilt_deg:
            _append_issue(
                Issue(
                    code="SG_TILT_001",
                    title="姿态不可达",
                    description=f"A/B 倾角 {max_tilt:.2f}° 超出安全包络 {machine_cfg.max_tilt_deg}°",
                    severity=Severity.blocker,
                    category="safety_gate",
                    dimension="D1",
                    line_range=(line_no, line_no),
                    evidence={"max_tilt_deg": max_tilt, "limit_deg": machine_cfg.max_tilt_deg},
                    suggestion="降低 A/B 轴倾角上限或改用分度加工策略；检查后处理五轴限制配置。",
                )
            )

    def _low_z_rotary_blocker(line_no: int, z_min: float, ra: float, rb: float, rc: float) -> None:
        rotary_jump = max(abs(ra), abs(rb), abs(rc))
        if z_min < safe_z and rotary_jump > machine_cfg.max_low_z_rotary_jump_deg:
            _append_issue(
                Issue(
                    code="SG_ROT_001",
                    title="低高度旋转跳变过大",
                    description=f"Safe Z({safe_z}mm) 以下发生较大旋转轴跳变 {rotary_jump:.2f}°",
                    severity=Severity.blocker,
                    category="safety_gate",
                    dimension="D1",
                    line_range=(line_no, line_no),
                    evidence={"rotary_jump_deg": rotary_jump, "limit_deg": machine_cfg.max_low_z_rotary_jump_deg, "z_min_mm": z_min},
                    suggestion="在低高度区间降低旋转轴步进；或先抬刀到 Safe Z 再旋转。",
                )
            )

    def _low_z_rapid_blocker(line_no: int, z_min: float, xy_move: float) -> None:
        if z_min < safe_z and xy_move >= low_z_blocker_xy:
            _append_issue(
                Issue(
                    code="SG_RAP_001",
                    title="危险区域快移",
                    description=f"Safe Z({safe_z}mm) 以下发生 G0 XY 大范围快移",
                    severity=Severity.blocker,
                    category="safety_gate",
                    dimension="D1",
                    line_range=(line_no, line_no),
                    evidence={"safe_z_mm": safe_z, "xy_move_mm": xy_move, "z_min_mm": z_min, "blocker_xy_mm": low_z_blocker_xy},
                    suggestion="大范围移动前先抬刀到 Safe Z 以上，避免跨区域穿越工件/夹具。",
                )
            )

    it = iter(lines)
    line_no = 0
    while True:
        if max_lines is not None and line_no >= max_lines:
            extra = next(it, None)
            sampling_truncated = extra is not None
            break

        raw_line = next(it, None)
        if raw_line is None:
            break

        line_no += 1

        if on_progress and (line_no == 1 or line_no % max(1, int(progress_every)) == 0):
            on_progress({"lines": line_no})

        if line_no % 2000 == 0:
            _check_time()

        cleaned = _clean_line_fast(raw_line)
        if not cleaned:
            continue
        total_lines += 1

        if len(cleaned) > max_line_len_warn:
            long_lines.append(line_no)

        words, gcodes, mcodes = _parse_words(cleaned)

        if line_no <= max_check_lines:
            if 20 in gcodes or 21 in gcodes:
                need_units = False
            if 90 in gcodes or 91 in gcodes:
                need_abs = False
            if 17 in gcodes or 18 in gcodes or 19 in gcodes:
                need_plane = False

        for g in gcodes:
            if g not in supported_g:
                if len(unsupported_g_hits) < 50:
                    unsupported_g_hits.append((line_no, g))
        for m in mcodes:
            if m not in supported_m:
                if len(unsupported_m_hits) < 50:
                    unsupported_m_hits.append((line_no, m))

        if 90 in gcodes:
            modal_absolute = True
        if 91 in gcodes:
            modal_absolute = False
        if 17 in gcodes:
            modal_plane = "G17"
        if 18 in gcodes:
            modal_plane = "G18"
        if 19 in gcodes:
            modal_plane = "G19"
        for g in gcodes:
            if g in (0, 1, 2, 3):
                motion_mode = f"G{g}"

        if "F" in words:
            modal_feed = float(words["F"])
            if abs(modal_feed - last_feed) > 1e-9:
                feed_changes += 1
                last_feed = modal_feed

        has_axis = any(k in words for k in ("X", "Y", "Z", "A", "B", "C"))
        if not has_axis:
            continue

        sx, sy, sz, sa, sb, sc = x, y, z, a, b, c

        def _axis(letter: str, current: float) -> float:
            if letter not in words:
                return current
            v = float(words[letter])
            return v if modal_absolute else current + v

        x = _axis("X", x)
        y = _axis("Y", y)
        z = _axis("Z", z)
        a = _axis("A", a)
        b = _axis("B", b)
        c = _axis("C", c)

        dx = x - sx
        dy = y - sy
        dz = z - sz
        da = a - sa
        db = b - sb
        dc = c - sc
        length = (dx * dx + dy * dy + dz * dz) ** 0.5

        motion_segments += 1
        total_distance += length
        if length < 0.2:
            short_segments += 1
        if motion_mode == "G0":
            rapid_distance += length
            if z > sz + 0.5:
                retract_count += 1
        else:
            cut_distance += length

        _axis_limit_blocker(line_no, "x", x)
        _axis_limit_blocker(line_no, "y", y)
        _axis_limit_blocker(line_no, "z", z)
        _axis_limit_blocker(line_no, "a", a)
        _axis_limit_blocker(line_no, "b", b)
        _axis_limit_blocker(line_no, "c", c)
        _tilt_blocker(line_no, a, b)

        z_min = min(sz, z)
        xy_move = (dx * dx + dy * dy) ** 0.5
        _low_z_rapid_blocker(line_no, z_min, xy_move)
        _low_z_rotary_blocker(line_no, z_min, da, db, dc)

        if stop_on_blocker and blocker_count >= 1:
            break

        is_cut_low = motion_mode != "G0" and z_min < safe_z

        if pending_low_z_rapid is not None:
            prev_cut = bool(pending_low_z_rapid["prev_cut_low"])
            depth_like_prev = bool(pending_low_z_rapid["depth_like_prev"])
            next_cut = bool(is_cut_low)
            depth_like_next = abs(sz - pending_low_z_rapid["z_end"]) <= depth_tol
            is_local = bool(prev_cut and next_cut and depth_like_prev and depth_like_next)
            sev = Severity.medium if is_local else Severity.high if pending_low_z_rapid["xy_move"] >= low_z_high_xy else Severity.medium
            _append_issue(
                Issue(
                    code="D1_RAP_001",
                    title="Safe Z 以下快移",
                    description="Safe Z 以下发生 G0 XY 快移，需结合上下文确认是否存在穿越风险",
                    severity=sev,
                    category="safety",
                    dimension="D1",
                    line_range=(pending_low_z_rapid["line_no"], pending_low_z_rapid["line_no"]),
                    evidence={
                        "safe_z_mm": safe_z,
                        "xy_move_mm": pending_low_z_rapid["xy_move"],
                        "z_min_mm": pending_low_z_rapid["z_min"],
                        "is_local_reposition": is_local,
                        "prev_line": pending_low_z_rapid["prev_line"],
                        "next_line": line_no,
                    },
                    suggestion="若为跨区域移动，建议先抬刀到 Safe Z；若为局部换位，确认夹具/工件无干涉并控制路径。",
                )
            )
            pending_low_z_rapid = None

        if motion_mode == "G0" and z_min < safe_z and xy_move >= low_z_warn_xy and xy_move < low_z_blocker_xy:
            depth_like_prev = abs(sz - prev_end_z) <= depth_tol
            pending_low_z_rapid = {
                "line_no": line_no,
                "z_min": z_min,
                "xy_move": xy_move,
                "z_end": z,
                "prev_cut_low": prev_cut_low,
                "depth_like_prev": depth_like_prev,
                "prev_line": prev_line_no if prev_line_no > 0 else None,
            }

        prev_cut_low = is_cut_low
        prev_end_z = z
        prev_line_no = line_no

    if pending_low_z_rapid is not None and blocker_count == 0:
        sev = Severity.high if pending_low_z_rapid["xy_move"] >= low_z_high_xy else Severity.medium
        _append_issue(
            Issue(
                code="D1_RAP_001",
                title="Safe Z 以下快移",
                description="Safe Z 以下发生 G0 XY 快移，需结合上下文确认是否存在穿越风险",
                severity=sev,
                category="safety",
                dimension="D1",
                line_range=(pending_low_z_rapid["line_no"], pending_low_z_rapid["line_no"]),
                evidence={
                    "safe_z_mm": safe_z,
                    "xy_move_mm": pending_low_z_rapid["xy_move"],
                    "z_min_mm": pending_low_z_rapid["z_min"],
                    "is_local_reposition": False,
                    "prev_line": pending_low_z_rapid["prev_line"],
                    "next_line": None,
                },
                suggestion="若为跨区域移动，建议先抬刀到 Safe Z；若为局部换位，确认夹具/工件无干涉并控制路径。",
            )
        )

    rapid_ratio = rapid_distance / max(total_distance, 1e-9)
    short_ratio = short_segments / max(motion_segments, 1)
    retract_ratio = retract_count / max(motion_segments, 1)

    dimension_penalties: Dict[str, float] = {k: 0.0 for k in dim_weights.keys()}
    dimension_metrics: Dict[str, Any] = {}

    if blocker_count == 0:
        d1_pen = 0.0
        for it in issues:
            if it.dimension == "D1":
                if it.severity == Severity.high:
                    d1_pen += p_high
                elif it.severity == Severity.medium:
                    d1_pen += p_medium
                elif it.severity == Severity.low:
                    d1_pen += p_low
        dimension_penalties["D1"] = float(dimension_penalties.get("D1", 0.0)) + d1_pen

        d4_pen = 0.0
        if rapid_ratio > d4_rapid_high:
            issues.append(
                Issue(
                    code="D4_EFF_001",
                    title="空走比例过高",
                    description=f"空走比例 {rapid_ratio:.1%} 超过阈值 {d4_rapid_high:.1%}",
                    severity=Severity.high,
                    category="efficiency",
                    dimension="D4",
                    evidence={"rapid_ratio": rapid_ratio, "threshold": d4_rapid_high},
                    suggestion="优化刀路排序与分区策略，减少无效移动与回撤。",
                )
            )
            d4_pen += 2.0
        elif rapid_ratio > d4_rapid_warn:
            issues.append(
                Issue(
                    code="D4_EFF_002",
                    title="空走比例偏高",
                    description=f"空走比例 {rapid_ratio:.1%} 高于建议阈值 {d4_rapid_warn:.1%}",
                    severity=Severity.low,
                    category="efficiency",
                    dimension="D4",
                    evidence={"rapid_ratio": rapid_ratio, "threshold": d4_rapid_warn},
                    suggestion="尝试启用最短路径排序或合并相邻加工区域，降低空走。",
                )
            )
            d4_pen += p_low

        if short_ratio > d4_short_high:
            issues.append(
                Issue(
                    code="D4_EFF_003",
                    title="短线段密度过高",
                    description=f"短线段比例 {short_ratio:.1%} 超过阈值 {d4_short_high:.1%}",
                    severity=Severity.medium,
                    category="efficiency",
                    dimension="D4",
                    evidence={"short_segment_ratio": short_ratio, "threshold": d4_short_high},
                    suggestion="降低离散化密度或启用样条/圆弧拟合，减少碎段。",
                )
            )
            d4_pen += p_medium
        elif short_ratio > d4_short_warn:
            issues.append(
                Issue(
                    code="D4_EFF_004",
                    title="短线段偏多",
                    description=f"短线段比例 {short_ratio:.1%} 高于建议阈值 {d4_short_warn:.1%}",
                    severity=Severity.low,
                    category="efficiency",
                    dimension="D4",
                    evidence={"short_segment_ratio": short_ratio, "threshold": d4_short_warn},
                    suggestion="适当放宽曲线拟合公差并启用刀路平滑，提升效率。",
                )
            )
            d4_pen += p_low

        if feed_changes > d4_feed_warn:
            issues.append(
                Issue(
                    code="D4_EFF_005",
                    title="进给切换频繁",
                    description=f"进给切换 {feed_changes} 次，建议阈值 {d4_feed_warn} 次",
                    severity=Severity.low,
                    category="efficiency",
                    dimension="D4",
                    evidence={"feed_changes": feed_changes, "threshold": d4_feed_warn},
                    suggestion="按工序段统一进给策略，减少细碎 F 指令。",
                )
            )
            d4_pen += min(p_medium, (feed_changes - d4_feed_warn) * 0.02)

        if retract_ratio > d4_retract_warn:
            issues.append(
                Issue(
                    code="D4_EFF_006",
                    title="抬刀/回撤偏多",
                    description=f"抬刀比例 {retract_ratio:.1%} 高于建议阈值 {d4_retract_warn:.1%}",
                    severity=Severity.low,
                    category="efficiency",
                    dimension="D4",
                    evidence={"retract_ratio": retract_ratio, "threshold": d4_retract_warn},
                    suggestion="优化分区与连刀策略，减少不必要的抬刀与回撤。",
                )
            )
            d4_pen += p_low

        dimension_penalties["D4"] = float(dimension_penalties.get("D4", 0.0)) + float(d4_pen)
        dimension_metrics["D4"] = {
            "rapid_ratio": rapid_ratio,
            "short_segment_ratio": short_ratio,
            "feed_changes": feed_changes,
            "retract_ratio": retract_ratio,
        }

        d6_pen = 0.0
        if need_units:
            issues.append(
                Issue(
                    code="D6_MOD_001",
                    title="缺少单位模态声明",
                    description=f"程序前 {max_check_lines} 行未声明 G20/G21",
                    severity=Severity.medium,
                    category="gcode_quality",
                    dimension="D6",
                    line_range=(1, max_check_lines),
                    evidence={"check_lines": max_check_lines},
                    suggestion="建议在程序头部显式声明 G21 或 G20，避免控制器沿用上次状态。",
                )
            )
            d6_pen += p_medium
        if need_abs:
            issues.append(
                Issue(
                    code="D6_MOD_002",
                    title="缺少距离模式声明",
                    description=f"程序前 {max_check_lines} 行未声明 G90/G91",
                    severity=Severity.medium,
                    category="gcode_quality",
                    dimension="D6",
                    line_range=(1, max_check_lines),
                    evidence={"check_lines": max_check_lines},
                    suggestion="建议在程序头部显式声明 G90 或 G91，避免出现增量/绝对解释错误。",
                )
            )
            d6_pen += p_medium
        if need_plane:
            issues.append(
                Issue(
                    code="D6_MOD_003",
                    title="缺少平面声明",
                    description=f"程序前 {max_check_lines} 行未声明 G17/G18/G19",
                    severity=Severity.low,
                    category="gcode_quality",
                    dimension="D6",
                    line_range=(1, max_check_lines),
                    evidence={"check_lines": max_check_lines},
                    suggestion="建议在程序头部显式声明平面（常见为 G17），提升可移植性。",
                )
            )
            d6_pen += p_low

        if unsupported_g_hits:
            issues.append(
                Issue(
                    code="D6_CTL_001",
                    title="存在不支持的 G 代码",
                    description=f"发现 {len(unsupported_g_hits)} 处不在支持列表的 G 指令",
                    severity=Severity.medium if len(unsupported_g_hits) < 5 else Severity.high,
                    category="gcode_quality",
                    dimension="D6",
                    line_range=(min(ln for ln, _ in unsupported_g_hits), max(ln for ln, _ in unsupported_g_hits)),
                    evidence={"hits": [{"line": ln, "g": code} for ln, code in unsupported_g_hits[:20]]},
                    suggestion="核对后处理控制器目标与方言；必要时替换不兼容 G 指令。",
                )
            )
            d6_pen += p_high if len(unsupported_g_hits) >= 5 else p_medium

        if unsupported_m_hits:
            issues.append(
                Issue(
                    code="D6_CTL_002",
                    title="存在不支持的 M 代码",
                    description=f"发现 {len(unsupported_m_hits)} 处不在支持列表的 M 指令",
                    severity=Severity.medium if len(unsupported_m_hits) < 5 else Severity.high,
                    category="gcode_quality",
                    dimension="D6",
                    line_range=(min(ln for ln, _ in unsupported_m_hits), max(ln for ln, _ in unsupported_m_hits)),
                    evidence={"hits": [{"line": ln, "m": code} for ln, code in unsupported_m_hits[:20]]},
                    suggestion="核对机床/控制器对 M 指令的支持范围，替换不兼容指令或更新后处理模板。",
                )
            )
            d6_pen += p_high if len(unsupported_m_hits) >= 5 else p_medium

        if long_lines:
            issues.append(
                Issue(
                    code="D6_FMT_001",
                    title="单行过长",
                    description=f"存在 {len(long_lines)} 行长度过长，影响可读性与审查",
                    severity=Severity.low,
                    category="gcode_quality",
                    dimension="D6",
                    line_range=(min(long_lines), max(long_lines)),
                    evidence={"lines": long_lines[:30]},
                    suggestion="适当拆分长行，保持关键指令可审查性。",
                )
            )
            d6_pen += min(p_medium, len(long_lines) * 0.05)

        dimension_penalties["D6"] = float(dimension_penalties.get("D6", 0.0)) + float(d6_pen)
        dimension_metrics["D6"] = {
            "unsupported_g_count": len(unsupported_g_hits),
            "unsupported_m_count": len(unsupported_m_hits),
            "long_line_count": len(long_lines),
            "missing_modal_units": int(need_units),
            "missing_modal_abs": int(need_abs),
            "missing_modal_plane": int(need_plane),
        }

    dimension_scores = score_dimensions(dim_weights, dimension_penalties)
    if blocker_count > 0:
        dimension_scores = {k: 0.0 for k in dim_weights.keys()}
        total_score = 0.0
    else:
        total_score = round(sum(dimension_scores.values()), 2)

    issue_counts = compute_issue_counts(issues)
    conclusion = decide_conclusion(issue_counts, total_score, dimension_scores, thresholds)
    allow_continue = conclusion != Conclusion.red

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
            "total_lines": total_lines,
            "motion_segments": motion_segments,
            "rapid_distance_mm": round(rapid_distance, 6),
            "cut_distance_mm": round(cut_distance, 6),
            "total_distance_mm": round(total_distance, 6),
            "short_segments": short_segments,
            "feed_changes": feed_changes,
            "retract_count": retract_count,
            "rapid_ratio": round(rapid_ratio, 6),
            "short_segment_ratio": round(short_ratio, 6),
            "retract_ratio": round(retract_ratio, 6),
            "blocker_count": blocker_count,
            "dimension_metrics": dimension_metrics,
        },
        task_meta={
            "task_name": "toolpath-eval",
            "file_name": file_name,
            "software_source": software_source,
            "machine_model": machine_model or machine_cfg.machine_name,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "engine": "streaming",
            "sampling": {
                "sampled": max_lines is not None,
                "max_lines": max_lines,
                "truncated": sampling_truncated,
            },
        },
    )
    result.artifacts = build_artifacts(result)
    return result


def evaluate_fileobj(
    fileobj: io.BufferedIOBase,
    *,
    file_name: str = "",
    software_source: str = "",
    machine_model: str = "",
    max_lines: Optional[int] = None,
    on_progress: Optional[ProgressCallback] = None,
    progress_every: int = 500,
) -> EvaluationResult:
    cfg = load_rule_config()
    stream = _open_text_stream(fileobj)
    try:
        return evaluate_lines(
            stream,
            file_name=file_name,
            software_source=software_source,
            machine_model=machine_model,
            raw_cfg=cfg,
            max_lines=max_lines,
            on_progress=on_progress,
            progress_every=progress_every,
        )
    finally:
        try:
            stream.detach()
        except Exception:
            pass
