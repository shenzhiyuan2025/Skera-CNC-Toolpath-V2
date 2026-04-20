from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from ..models import GCodeBlock, Issue, Severity


def analyze_d6(blocks: List[GCodeBlock], supported: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[List[Issue], Dict[str, Any], float]:
    issues: List[Issue] = []
    d6_cfg = cfg.get("d6_rules", {})
    supported_g = set(int(x) for x in supported.get("gcodes", []))
    supported_m = set(int(x) for x in supported.get("mcodes", []))

    max_check_lines = int(d6_cfg.get("missing_modal_decl_check_lines", 30))
    need_units = True
    need_abs = True
    need_plane = True

    unsupported_g_hits: List[Tuple[int, int]] = []
    unsupported_m_hits: List[Tuple[int, int]] = []
    long_lines: List[int] = []

    for b in blocks:
        if b.line_no <= max_check_lines:
            if 20 in b.gcodes or 21 in b.gcodes:
                need_units = False
            if 90 in b.gcodes or 91 in b.gcodes:
                need_abs = False
            if 17 in b.gcodes or 18 in b.gcodes or 19 in b.gcodes:
                need_plane = False

        for g in b.gcodes:
            if int(g) not in supported_g:
                unsupported_g_hits.append((b.line_no, int(g)))
        for m in b.mcodes:
            if int(m) not in supported_m:
                unsupported_m_hits.append((b.line_no, int(m)))

        if len(b.cleaned) > int(d6_cfg.get("max_line_len_warn", 120)):
            long_lines.append(b.line_no)

    penalty = 0.0

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
        penalty += 1.5
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
        penalty += 1.5
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
        penalty += 0.6

    if unsupported_g_hits:
        uniq = {(ln, code) for ln, code in unsupported_g_hits}
        issues.append(
            Issue(
                code="D6_CTL_001",
                title="存在不支持的 G 代码",
                description=f"发现 {len(uniq)} 处不在支持列表的 G 指令",
                severity=Severity.medium if len(uniq) < 5 else Severity.high,
                category="gcode_quality",
                dimension="D6",
                line_range=(min(ln for ln, _ in uniq), max(ln for ln, _ in uniq)),
                evidence={"hits": [{"line": ln, "g": code} for ln, code in sorted(uniq)[:20]]},
                suggestion="核对后处理控制器目标与方言；必要时替换不兼容 G 指令。",
            )
        )
        penalty += 2.0 if len(uniq) >= 5 else 1.5

    if unsupported_m_hits:
        uniqm = {(ln, code) for ln, code in unsupported_m_hits}
        issues.append(
            Issue(
                code="D6_CTL_002",
                title="存在不支持的 M 代码",
                description=f"发现 {len(uniqm)} 处不在支持列表的 M 指令",
                severity=Severity.medium if len(uniqm) < 5 else Severity.high,
                category="gcode_quality",
                dimension="D6",
                line_range=(min(ln for ln, _ in uniqm), max(ln for ln, _ in uniqm)),
                evidence={"hits": [{"line": ln, "m": code} for ln, code in sorted(uniqm)[:20]]},
                suggestion="核对机床/控制器对 M 指令的支持范围，替换不兼容指令或更新后处理模板。",
            )
        )
        penalty += 2.0 if len(uniqm) >= 5 else 1.5

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
        penalty += min(1.2, len(long_lines) * 0.05)

    metrics_out = {
        "unsupported_g_count": len(set(unsupported_g_hits)),
        "unsupported_m_count": len(set(unsupported_m_hits)),
        "long_line_count": len(long_lines),
        "missing_modal_units": int(need_units),
        "missing_modal_abs": int(need_abs),
        "missing_modal_plane": int(need_plane),
    }
    return issues, metrics_out, penalty

