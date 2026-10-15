"""Wi-Fi model and backend detection. Backends run as the normal user (no sudo)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional

PERMISSION_FIX = {
    "networkmanager": "allow your user to manage NetworkManager (add it to the netdev group "
    "or a polkit rule; see README), then log out and back in",
    "wpa_supplicant": "run: sudo usermod -aG netdev $USER, then log out and back in",
}


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int
    secure: bool
    saved: bool = False
    active: bool = False


@dataclass(frozen=True)
class WifiStatus:
    ssid: Optional[str] = None
    signal: Optional[int] = None
    ip: Optional[str] = None


class WifiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def signal_bars(signal: Optional[int], ascii: bool = False) -> str:
    if signal is None:
        return "___"
    levels = 3 if signal >= 67 else 2 if signal >= 34 else 1
    glyphs = "###" if ascii else "▂▄▆"
    return glyphs[:levels] + "_" * (3 - levels)


def sort_networks(nets: list[Network]) -> list[Network]:
    best: dict = {}
    for n in nets:
        if not n.ssid:
            continue
        cur = best.get(n.ssid)
        if cur is None or (n.active, n.signal) > (cur.active, cur.signal):
            best[n.ssid] = n
    return sorted(best.values(), key=lambda n: (not n.active, -n.signal, n.ssid))


def detect_backend(
    interface: str = "wlan0",
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], Optional[str]] = shutil.which,
):
    from beepy_gpt.client.wifi.nm import NmBackend
    from beepy_gpt.client.wifi.wpa import WpaBackend

    try:
        if which("nmcli"):
            p = run(["nmcli", "-t", "-f", "RUNNING", "general"], capture_output=True, text=True, timeout=10)
            if p.returncode == 0 and p.stdout.strip() == "running":
                return NmBackend(interface, run=run)
        if which("wpa_cli"):
            p = run(["wpa_cli", "-i", interface, "ping"], capture_output=True, text=True, timeout=10)
            if "PONG" in (p.stdout or ""):
                return WpaBackend(interface, run=run)
    except (OSError, subprocess.SubprocessError):
        return None
    return None
