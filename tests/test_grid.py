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


def test_combining_marks_and_variation_selectors_keep_alignment():
    g = Grid(cols=4, rows=1)
    g.put(0, 0, "á️b")
    assert g.row_text(0) == "a??b"


def test_lone_surrogate_and_line_separators_are_replaced():
    g = Grid(cols=4, rows=1)
    g.put(0, 0, "\ud800")
    assert g.row_text(0)[0] == "?"
    assert g.row_text(0).encode("utf-8")
    g.put(0, 1, "a b")
    assert g.row_text(0) == "?a?b"


def test_snapshot_keeps_cells_with_separators():
    g = Grid(cols=5, rows=1)
    g.put(0, 0, "a b")
    assert g.snapshot().split("\n")[0] == "a?b"


def test_bottom_right_cell_writable():
    g = Grid()
    assert g.put(29, 49, "x") == 50
    assert g.row_text(29)[49] == "x"


def test_to_ascii_dashes_and_quotes():
    assert to_ascii("a—b") == "a-b"
    assert to_ascii("a–b") == "a-b"
    assert to_ascii("‘x’ “y”") == "'x' \"y\""


def test_fit_zero_width():
    assert fit("abc", 0) == ""
    assert fit("abc", -1) == ""
