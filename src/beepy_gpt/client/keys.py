"""Key normalization. The app only reacts to keys a Beepy can produce easily."""

from __future__ import annotations

import curses
from typing import Optional, Union

UP, DOWN, LEFT, RIGHT = "UP", "DOWN", "LEFT", "RIGHT"
ENTER, BACK, BACKSPACE = "ENTER", "BACK", "BACKSPACE"
NAV = {UP, DOWN, LEFT, RIGHT, ENTER, BACK, BACKSPACE}

_SPECIAL = {
    curses.KEY_UP: UP, curses.KEY_DOWN: DOWN, curses.KEY_LEFT: LEFT, curses.KEY_RIGHT: RIGHT,
    curses.KEY_ENTER: ENTER, curses.KEY_BACKSPACE: BACKSPACE, curses.KEY_RESIZE: "RESIZE",
}


def normalize(ch: Union[str, int]) -> Optional[str]:
    if isinstance(ch, int):
        if ch in _SPECIAL:
            return _SPECIAL[ch]
        if curses.KEY_F0 <= ch <= curses.KEY_F0 + 63:
            return f"F{ch - curses.KEY_F0}"
        return None
    if ch in ("\n", "\r"):
        return ENTER
    if ch == "\x1b":
        return BACK
    if ch in ("\x7f", "\x08"):
        return BACKSPACE
    if ch == "\t":
        return "TAB"
    if len(ch) == 1 and ord(ch) < 32:
        return f"CTRL-{chr(ord(ch) + 64)}"
    if len(ch) == 1 and ch.isprintable():
        return ch
    return None


def beepy_producible(key: str) -> bool:
    return key in NAV or (len(key) == 1 and key.isprintable())
