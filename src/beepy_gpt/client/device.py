"""Beepy firmware sysfs: battery readings and the RGB LED. Degrades to a no-op."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Union

log = logging.getLogger(__name__)


class Device:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._warned: set = set()

    @property
    def available(self) -> bool:
        return (self.root / "battery_volts").exists()

    def _read(self, name: str) -> Optional[str]:
        try:
            return (self.root / name).read_text().strip()
        except OSError:
            return None

    def _write(self, name: str, value: str) -> None:
        try:
            (self.root / name).write_text(value)
        except OSError as e:
            if name not in self._warned:
                self._warned.add(name)
                log.warning("cannot write %s: %s", self.root / name, e)

    def led_writable(self) -> bool:
        # The firmware's sysfs files are root-only unless a udev rule opens them up.
        return os.access(self.root / "led", os.W_OK)

    def read_battery(self) -> Optional[tuple[int, float]]:
        try:
            return int(self._read("battery_percent") or ""), float(self._read("battery_volts") or "")
        except ValueError:
            return None

    def set_led_alert(self, on: bool) -> None:
        if on:
            self._write("led_red", "0")
            self._write("led_green", "0")
            self._write("led_blue", "255")
            self._write("led", "3")  # firmware: flash until next keypress
        else:
            self._write("led", "0")


class NullDevice:
    available = False

    def read_battery(self) -> Optional[tuple[int, float]]:
        return None

    def set_led_alert(self, on: bool) -> None:
        return None


def open_device(root: Path) -> Union[Device, NullDevice]:
    d = Device(root)
    if d.available:
        return d
    log.info("no Beepy firmware sysfs at %s: battery and LED hidden", root)
    return NullDevice()
