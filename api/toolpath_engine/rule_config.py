from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .models import AxisLimit, MachineConfig


def _config_path() -> Path:
    return Path(__file__).resolve().parent / "configs" / "default_rules.json"


def load_rule_config() -> Dict[str, Any]:
    with _config_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_machine_config(raw_cfg: Dict[str, Any]) -> MachineConfig:
    machine = raw_cfg["machine_config"]
    limits = {
        axis: AxisLimit(minimum=float(v["minimum"]), maximum=float(v["maximum"]))
        for axis, v in machine["axis_limits"].items()
    }
    return MachineConfig(
        machine_id=machine["machine_id"],
        machine_name=machine["machine_name"],
        axis_limits=limits,
        safe_z_mm=float(machine["safe_z_mm"]),
        max_tilt_deg=float(machine["max_tilt_deg"]),
        max_low_z_rotary_jump_deg=float(machine["max_low_z_rotary_jump_deg"]),
        dangerous_rapid_xy_mm=float(machine["dangerous_rapid_xy_mm"]),
    )
