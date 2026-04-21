from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, List, Tuple

from .machine_state import apply_modal_and_state, state_delta
from .models import GCodeBlock, MachineState, MotionSegment


def _segment_length(start: Dict[str, float], end: Dict[str, float]) -> float:
    return math.sqrt(
        (end["x"] - start["x"]) ** 2
        + (end["y"] - start["y"]) ** 2
        + (end["z"] - start["z"]) ** 2
    )


def build_motion_segments(blocks: List[GCodeBlock]) -> Tuple[List[MotionSegment], Dict[str, Any]]:
    state = MachineState()
    segments: List[MotionSegment] = []

    metrics: Dict[str, Any] = {
        "total_lines": len(blocks),
        "motion_segments": 0,
        "rapid_distance_mm": 0.0,
        "cut_distance_mm": 0.0,
        "total_distance_mm": 0.0,
        "short_segments": 0,
        "feed_changes": 0,
        "retract_count": 0,
    }

    last_feed = state.modal.feed

    for idx, block in enumerate(blocks):
        start_state = replace(state)
        state = apply_modal_and_state(state, block)
        delta = state_delta(start_state, state)
        has_axis_motion = any(abs(delta[k]) > 1e-9 for k in ("x", "y", "z", "a", "b", "c"))

        if abs(state.modal.feed - last_feed) > 1e-9:
            metrics["feed_changes"] += 1
            last_feed = state.modal.feed

        if not has_axis_motion:
            continue

        mode = state.modal.motion_mode
        seg = MotionSegment(
            segment_id=f"S{idx+1}",
            line_no=block.line_no,
            mode=mode,
            start=start_state.to_axes(),
            end=state.to_axes(),
            feed=None if mode == "G0" else state.modal.feed,
            length_mm=_segment_length(start_state.to_axes(), state.to_axes()),
            meta={
                "delta": delta,
                "plane": state.modal.plane,
                "gcodes": block.gcodes,
                "mcodes": block.mcodes,
            },
        )
        segments.append(seg)
        metrics["motion_segments"] += 1
        metrics["total_distance_mm"] += seg.length_mm
        if seg.length_mm < 0.2:
            metrics["short_segments"] += 1
        if mode == "G0":
            metrics["rapid_distance_mm"] += seg.length_mm
            if seg.end["z"] > seg.start["z"] + 0.5:
                metrics["retract_count"] += 1
        else:
            metrics["cut_distance_mm"] += seg.length_mm

    metrics["rapid_ratio"] = (
        metrics["rapid_distance_mm"] / max(metrics["total_distance_mm"], 1e-9)
    )
    metrics["short_segment_ratio"] = (
        metrics["short_segments"] / max(metrics["motion_segments"], 1)
    )
    metrics["retract_ratio"] = (
        metrics["retract_count"] / max(metrics["motion_segments"], 1)
    )
    return segments, metrics
