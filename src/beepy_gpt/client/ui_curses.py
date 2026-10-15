"""curses front end (lite tier): draws the Grid, feeds keys to the App."""

from __future__ import annotations

import curses
import os
import queue
import subprocess
from datetime import datetime
from typing import Any

from beepy_gpt.client.keys import beepy_producible, normalize
from beepy_gpt.client.render.grid import BOLD, REVERSE, Grid

_ATTR = {0: curses.A_NORMAL, BOLD: curses.A_BOLD, REVERSE: curses.A_REVERSE,
         BOLD | REVERSE: curses.A_BOLD | curses.A_REVERSE}


def draw(win: Any, grid: Grid, top: int = 0, left: int = 0) -> None:
    for r in range(grid.rows):
        for col, text, attr in grid.runs(r):
            try:
                win.addstr(top + r, left + col, text, _ATTR[attr])
            except curses.error:
                pass  # writing the bottom-right cell moves the cursor off-screen


def run(app: Any, events: "queue.Queue[dict]", frame: Any = None) -> None:
    os.environ.setdefault("ESCDELAY", "25")

    def main(stdscr: Any) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        stdscr.timeout(200)
        dirty, minute = True, None
        while app.running:
            while True:
                try:
                    app.on_event(events.get_nowait())
                    dirty = True
                except queue.Empty:
                    break
            if app.external:
                cmd, app.external = app.external, None
                curses.def_prog_mode()
                curses.endwin()
                subprocess.call(cmd)
                curses.reset_prog_mode()
                stdscr.refresh()
                dirty = True
            now = datetime.now()
            if frame is not None:
                dirty = frame.tick(now) or dirty
            if now.minute != minute:
                minute, dirty = now.minute, True
            if dirty:
                grid = app.render(now)
                stdscr.erase()
                if frame is not None:
                    frame.draw(stdscr, grid)
                else:
                    draw(stdscr, grid)
                stdscr.refresh()
                dirty = False
            try:
                ch = stdscr.get_wch()
            except curses.error:
                continue
            key = normalize(ch)
            if key is None:
                continue
            if key == "RESIZE":
                dirty = True
                continue
            if frame is not None and frame.handle_key(key):
                dirty = True
                continue
            if not beepy_producible(key):
                if frame is not None:
                    frame.refuse(key)
                    dirty = True
                continue
            app.on_key(key)
            dirty = True

    curses.wrapper(main)
