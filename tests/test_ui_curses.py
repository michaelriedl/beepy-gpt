import curses

from beepy_gpt.client.render.grid import BOLD, REVERSE, Grid
from beepy_gpt.client.ui_curses import draw


class Win:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def addstr(self, y, x, text, attr=0):
        if self.fail_at and (y, x + len(text) - 1) == self.fail_at:
            raise curses.error("bottom-right")
        self.calls.append((y, x, text, attr))


def test_draw_maps_attributes():
    g = Grid(cols=6, rows=1)
    g.put(0, 0, "ab", BOLD)
    g.put(0, 2, "cd", REVERSE)
    w = Win()
    draw(w, g, top=1, left=2)
    assert w.calls == [(1, 2, "ab", curses.A_BOLD), (1, 4, "cd", curses.A_REVERSE), (1, 6, "  ", curses.A_NORMAL)]


def test_bottom_right_cell_error_is_ignored():
    g = Grid(cols=4, rows=2)
    g.put(1, 0, "wxyz")
    w = Win(fail_at=(1, 3))
    draw(w, g)  # must not raise
    assert w.calls == [(0, 0, "    ", curses.A_NORMAL)]  # the other row was still drawn
