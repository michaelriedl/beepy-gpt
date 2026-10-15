"""A 50x30 cell grid with only NORMAL/BOLD/REVERSE attributes (1-bit Sharp LCD)."""

from __future__ import annotations

import unicodedata

from beepy_gpt.client.render.text import to_ascii

NORMAL, BOLD, REVERSE = 0, 1, 2
_ALLOWED = BOLD | REVERSE
COLS, ROWS = 50, 30
# Control, format, marks (zero-width), surrogates, private use, unassigned, line/paragraph separators.
_UNSAFE_CATEGORIES = frozenset(("Cc", "Cf", "Mn", "Me", "Mc", "Cs", "Co", "Cn", "Zl", "Zp"))
_SNAP = {NORMAL: " ", BOLD: "b", REVERSE: "r", BOLD | REVERSE: "B"}


class MonochromeError(ValueError):
    """An attribute the 1-bit display cannot show."""


def safe_char(ch: str) -> str:
    if len(ch) != 1 or ord(ch) > 0xFFFF:
        return "?"
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return "?"
    if unicodedata.category(ch) in _UNSAFE_CATEGORIES:
        return "?"
    return ch


class Grid:
    def __init__(self, cols: int = COLS, rows: int = ROWS, ascii: bool = False):
        self.cols, self.rows, self.ascii = cols, rows, ascii
        self._ch = [[" "] * cols for _ in range(rows)]
        self._at = [[NORMAL] * cols for _ in range(rows)]

    def put(self, row: int, col: int, text: str, attr: int = NORMAL) -> int:
        if attr & ~_ALLOWED:
            raise MonochromeError(f"attribute {attr} not allowed on a monochrome display")
        if not 0 <= row < self.rows:
            return col
        if self.ascii:
            text = to_ascii(text)
        for ch in text:
            if col >= self.cols:
                break
            if col >= 0:
                self._ch[row][col] = safe_char(ch)
                self._at[row][col] = attr
            col += 1
        return col

    def fill_attr(self, row: int, attr: int) -> None:
        if attr & ~_ALLOWED:
            raise MonochromeError(f"attribute {attr} not allowed on a monochrome display")
        if 0 <= row < self.rows:
            self._at[row] = [attr] * self.cols

    def row_text(self, row: int) -> str:
        return "".join(self._ch[row])

    def attr(self, row: int, col: int) -> int:
        return self._at[row][col]

    def runs(self, row: int) -> list[tuple[int, str, int]]:
        out: list[tuple[int, str, int]] = []
        start = 0
        for c in range(1, self.cols + 1):
            if c == self.cols or self._at[row][c] != self._at[row][start]:
                out.append((start, "".join(self._ch[row][start:c]), self._at[row][start]))
                start = c
        return out

    def snapshot(self) -> str:
        text = [self.row_text(r).rstrip(" ") for r in range(self.rows)]
        attrs = ["".join(_SNAP[a] for a in self._at[r]).rstrip(" ") for r in range(self.rows)]
        return "\n".join(text) + "\n----\n" + "\n".join(attrs)
