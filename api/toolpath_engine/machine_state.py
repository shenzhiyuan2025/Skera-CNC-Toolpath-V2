from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional

from .models import GCodeBlock, MachineState, ModalState


def apply_modal_and_state(state: MachineState, block: GCodeBlock) -> MachineState:
    modal = state.modal
    words = block.words

    if 20 in block.gcodes:
        modal = replace(modal, units_mm=False)
    if 21 in block.gcodes:
        modal = replace(modal, units_mm=True)
    if 90 in block.gcodes:
        modal = replace(modal, absolute_mode=True)
    if 91 in block.gcodes:
        modal = replace(modal, absolute_mode=False)

    if 17 in block.gcodes:
        modal = replace(modal, plane="G17")
    if 18 in block.gcodes:
        modal = replace(modal, plane="G18")
    if 19 in block.gcodes:
        modal = replace(modal, plane="G19")

    for g in block.gcodes:
        if g in (0, 1, 2, 3):
            modal = replace(modal, motion_mode=f"G{g}")

    if "F" in words:
        modal = replace(modal, feed=float(words["F"]))
    if "S" in words:
        modal = replace(modal, spindle_speed=float(words["S"]))
    if "T" in words:
        modal = replace(modal, tool=str(int(words["T"])))

    spindle_on = modal.spindle_on
    for m in block.mcodes:
        if m in (3, 4):
            spindle_on = True
        elif m == 5:
            spindle_on = False
    if spindle_on != modal.spindle_on:
        modal = replace(modal, spindle_on=spindle_on)

    def _target(axis_letter: str, current: float) -> Optional[float]:
        if axis_letter not in words:
            return None
        val = float(words[axis_letter])
        return val if modal.absolute_mode else current + val

    x = _target("X", state.x)
    y = _target("Y", state.y)
    z = _target("Z", state.z)
    a = _target("A", state.a)
    b = _target("B", state.b)
    c = _target("C", state.c)

    new_state = MachineState(
        x=state.x if x is None else x,
        y=state.y if y is None else y,
        z=state.z if z is None else z,
        a=state.a if a is None else a,
        b=state.b if b is None else b,
        c=state.c if c is None else c,
        modal=modal,
    )
    return new_state


def state_delta(start: MachineState, end: MachineState) -> Dict[str, float]:
    s = start.to_axes()
    e = end.to_axes()
    return {k: e[k] - s[k] for k in s.keys()}
