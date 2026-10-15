"""Text layout helpers for a fixed-width monochrome screen."""

from __future__ import annotations

import textwrap

_ASCII = str.maketrans({
    "●": "*", "○": "o", "✕": "x", "▶": ">", "✓": "+", "✗": "x", "…": "~", "─": "-",
    "▂": "#", "▄": "#", "▆": "#", "·": "-", "▏": "|", "↵": "<", "↑": "^", "↓": "v",
})


def wrap(text: str, width: int, indent: str = "") -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(
            para, width=width, subsequent_indent=indent, break_long_words=True,
            break_on_hyphens=False, replace_whitespace=False,
        ) or [""])
    return lines


def chunks(text: str, width: int) -> list[str]:
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


def fit(text: str, width: int) -> str:
    return text.ljust(width) if len(text) <= width else text[: width - 1] + "…"


def to_ascii(text: str) -> str:
    out = text.translate(_ASCII)
    return "".join(c if ord(c) < 128 else "?" for c in out)
