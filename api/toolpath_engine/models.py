from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Severity(str, Enum):
    blocker = "blocker"
    high = "high"
    medium = "medium"
    low = "low"


class Conclusion(str, Enum):
    green = "green"
    yellow = "yellow"
    red = "red"


@dataclass
class AxisLimit:
    minimum: float
    maximum: float


@dataclass
class ToolDefinition:
    tool_id: str
    name: str
    diameter_mm: float
    stickout_mm: float = 0.0


@dataclass
class FixtureDefinition:
    fixture_id: str
    name: str
    envelope: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkpieceDefinition:
    workpiece_id: str
    name: str
    envelope: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MachineConfig:
    machine_id: str
    machine_name: str
    axis_limits: Dict[str, AxisLimit]
    safe_z_mm: float
    max_tilt_deg: float
    max_low_z_rotary_jump_deg: float
    dangerous_rapid_xy_mm: float


@dataclass
class GCodeBlock:
    line_no: int
    raw: str
    cleaned: str
    words: Dict[str, float]
    gcodes: List[int]
    mcodes: List[int]


@dataclass
class ModalState:
    absolute_mode: bool = True
    units_mm: bool = True
    plane: str = "G17"
    motion_mode: str = "G0"
    feed: float = 1200.0
    spindle_speed: float = 0.0
    spindle_on: bool = False
    tool: Optional[str] = None


@dataclass
class MachineState:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    modal: ModalState = field(default_factory=ModalState)

    def to_axes(self) -> Dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "a": self.a,
            "b": self.b,
            "c": self.c,
        }


@dataclass
class MotionSegment:
    segment_id: str
    line_no: int
    mode: str
    start: Dict[str, float]
    end: Dict[str, float]
    feed: Optional[float]
    length_mm: float
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Issue:
    code: str
    title: str
    description: str
    severity: Severity
    category: str
    dimension: str
    line_range: Optional[Tuple[int, int]] = None
    segment_range: Optional[Tuple[str, str]] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""


@dataclass
class DimensionScore:
    dimension: str
    score: float
    max_score: float
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationSummary:
    final_conclusion: Conclusion
    allow_continue: bool
    summary: str
    total_score: float
    issue_counts: Dict[str, int]


@dataclass
class EvaluationResult:
    final_conclusion: Conclusion
    allow_continue: bool
    summary: str
    total_score: float
    dimension_scores: Dict[str, float]
    issue_counts: Dict[str, int]
    issues: List[Issue]
    artifacts: Dict[str, str]
    metrics: Dict[str, Any]
    task_meta: Dict[str, Any] = field(default_factory=dict)
