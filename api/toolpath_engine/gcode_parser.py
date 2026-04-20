from __future__ import annotations

import re
from typing import Dict, List

from .models import GCodeBlock

TOKEN_PATTERN = re.compile(r"([A-Za-z])\s*([-+]?\d+(?:\.\d+)?)")


def clean_line(line: str) -> str:
    no_semicolon = line.split(";")[0]
    return re.sub(r"\([^)]*\)", "", no_semicolon).strip().upper()


def parse_gcode(gcode_text: str) -> List[GCodeBlock]:
    blocks: List[GCodeBlock] = []
    for line_no, raw in enumerate(gcode_text.splitlines(), start=1):
        cleaned = clean_line(raw)
        if not cleaned:
            continue
        tokens = TOKEN_PATTERN.findall(cleaned)
        words: Dict[str, float] = {}
        gcodes: List[int] = []
        mcodes: List[int] = []
        for letter, num in tokens:
            letter_u = letter.upper()
            value = float(num)
            words[letter_u] = value
            if letter_u == "G":
                gcodes.append(int(value))
            elif letter_u == "M":
                mcodes.append(int(value))
        blocks.append(
            GCodeBlock(
                line_no=line_no,
                raw=raw,
                cleaned=cleaned,
                words=words,
                gcodes=gcodes,
                mcodes=mcodes,
            )
        )
    return blocks
