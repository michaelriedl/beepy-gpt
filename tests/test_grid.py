import pytest

from beepy_gpt.client.render.grid import BOLD, NORMAL, REVERSE, Grid, MonochromeError, safe_char
from beepy_gpt.client.render.text import chunks, fit, to_ascii, wrap


def test_put_clips_and_returns_next_col():
    g = Grid(cols=10, rows=2)
    assert g.put(0, 7, "abcdef") == 10
    assert g.row_text(0) == "       abc"
    assert g.put(5, 0, "x") == 0  # row out of range is ignored


def test_monochrome_guard():
    g = Grid()
    with pytest.raises(MonochromeError):
        g.put(0, 0, "x", 4)
    g.put(0, 0, "x", BOLD | REVERSE)


def test_wide_chars_replaced():
    assert safe_char("界") == "?" and safe_char("😀") == "?" and safe_char("\x07") == "?"
    g = Grid(cols=6, rows=1)
    g.put(0, 0, "a界😀b")
    assert g.row_text(0) == "a??b  "


def test_runs_and_snapshot():
    g = Grid(cols=6, rows=2)
    g.put(0, 0, "ab", BOLD)
    g.put(0, 2, "cd", REVERSE)
    g.fill_attr(1, REVERSE)
    assert g.runs(0) == [(0, "ab", BOLD), (2, "cd", REVERSE), (4, "  ", NORMAL)]
    assert g.snapshot() == "abcd\n\n----\nbbrr\nrrrrrr"


def test_ascii_mode():
    g = Grid(cols=8, rows=1, ascii=True)
    g.put(0, 0, "●▶✓ö")
    assert g.row_text(0) == "*>+?    "


def test_wrap_keeps_newlines_and_indent():
    assert wrap("aaa bbb ccc", 7, "  ") == ["aaa bbb", "  ccc"]
    assert wrap("x\n\ny", 10) == ["x", "", "y"]
    assert wrap("abcdefghij", 4) == ["abcd", "efgh", "ij"]


def test_chunks_and_fit():
    assert chunks("abcdef", 4) == ["abcd", "ef"]
    assert chunks("", 4) == [""]
    assert fit("abc", 5) == "abc  "
    assert fit("abcdef", 5) == "abcd…"


def test_to_ascii():
    assert to_ascii("─▂▄▆…") == "-###~"
