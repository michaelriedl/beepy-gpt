"""Desktop emulator: Beepy-sized frame, fake firmware sysfs, refused-key display."""

from __future__ import annotations

import atexit
import curses
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from beepy_gpt.client.render.grid import Grid
from beepy_gpt.client.ui_curses import draw

LED_MODES = {"0": "off", "1": "on", "2": "flash", "3": "flash-until-key"}


def percent_for(volts: float) -> int:
    return max(0, min(100, round((volts - 3.30) / (4.20 - 3.30) * 100)))


class Emulator:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._last = clock()
        self.sysfs_root = Path(tempfile.mkdtemp(prefix="bgpt-sysfs-"))
        atexit.register(shutil.rmtree, self.sysfs_root, True)
        self.volts = 3.90
        self.charging = False
        self.refused: Optional[str] = None
        for name in ("led", "led_red", "led_green", "led_blue"):
            (self.sysfs_root / name).write_text("0")
        self._write_battery()

    def _write_battery(self) -> None:
        (self.sysfs_root / "battery_volts").write_text(f"{self.volts:.3f}".rstrip("0").rstrip("."))
        (self.sysfs_root / "battery_percent").write_text(str(percent_for(self.volts)))
        (self.sysfs_root / "battery_raw").write_text(str(int(self.volts * 600)))

    def handle_key(self, key: str) -> bool:
        if key == "F5":
            self.volts = round(max(3.0, self.volts - 0.05), 3)
        elif key == "F6":
            self.volts = round(min(4.25, self.volts + 0.05), 3)
        elif key == "F7":
            self.charging = not self.charging
        else:
            return False
        self._write_battery()
        return True

    def refuse(self, key: str) -> None:
        self.refused = key

    def tick(self, now: datetime) -> bool:
        t = self._clock()
        steps = int((t - self._last) // 10)
        if steps <= 0:
            return False
        self._last += steps * 10
        self.volts = round(self.volts + steps * (0.002 if self.charging else -0.0005), 4)
        self._write_battery()
        return True

    def _read(self, name: str) -> str:
        try:
            return (self.sysfs_root / name).read_text().strip()
        except OSError:
            return "?"

    def led_state(self) -> str:
        mode = LED_MODES.get(self._read("led"), "?")
        if mode == "off":
            return "off"
        rgb = (self._read("led_red"), self._read("led_green"), self._read("led_blue"))
        color = {("0", "0", "255"): "blue", ("255", "0", "0"): "red", ("0", "255", "0"): "green"}.get(rgb, "/".join(rgb))
        return f"{mode} {color}"

    def panel_lines(self) -> list[str]:
        lines = [
            "BEEPY EMULATOR",
            "",
            f"battery {self.volts:.3f}V {percent_for(self.volts)}%",
            f"charging {'on' if self.charging else 'off'}",
            f"LED {self.led_state()}",
            "",
            "F5/F6 volts -/+",
            "F7    charging",
            "Esc   Back key",
        ]
        if self.refused:
            lines += ["", f"refused: {self.refused}", "(not on Beepy)"]
        return lines

    def draw(self, win: Any, grid: Grid) -> None:
        h, w = win.getmaxyx()
        if h < grid.rows + 2 or w < 80:
            win.addstr(0, 0, f"terminal too small: need 80x{grid.rows + 2}, have {w}x{h}")
            return
        top = "┌" + "─" * grid.cols + "┐"
        win.addstr(0, 0, top)
        for r in range(grid.rows):
            win.addstr(r + 1, 0, "│")
            win.addstr(r + 1, grid.cols + 1, "│")
        try:
            win.addstr(grid.rows + 1, 0, "└" + "─" * grid.cols + "┘")
        except curses.error:
            pass
        draw(win, grid, top=1, left=1)
        for i, line in enumerate(self.panel_lines()):
            win.addstr(1 + i, grid.cols + 4, line[: w - grid.cols - 5])
