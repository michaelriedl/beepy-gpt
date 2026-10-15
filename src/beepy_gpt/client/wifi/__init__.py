"""Wi-Fi model and backend detection. Backends run as the normal user (no sudo)."""

from __future__ import annotations

import os
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


BAR_GLYPHS = "▂▄▆"


def signal_bars(signal: Optional[int], ascii: bool = False) -> str:
    if signal is None:
        return "___"
    levels = 3 if signal >= 67 else 2 if signal >= 34 else 1
    glyphs = "###" if ascii else BAR_GLYPHS
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


# A normal user's PATH on Raspberry Pi OS leaves out the sbin directories, where wpa_cli lives.
_SBIN_DIRS = ("/usr/sbin", "/sbin")


def find_tool(
    name: str,
    which: Callable[[str], Optional[str]] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> Optional[str]:
    found = which(name)
    if found:
        return found
    for d in _SBIN_DIRS:
        path = os.path.join(d, name)
        if is_file(path):
            return path
    return None


def detect_backend(
    interface: str = "wlan0",
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], Optional[str]] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
):
    from beepy_gpt.client.wifi.nm import NmBackend
    from beepy_gpt.client.wifi.wpa import WpaBackend

    try:
        nmcli = find_tool("nmcli", which, is_file)
        if nmcli:
            p = run([nmcli, "-t", "-f", "RUNNING", "general"], capture_output=True, text=True, timeout=10)
            if p.returncode == 0 and p.stdout.strip() == "running":
                return NmBackend(interface, run=run, tool=nmcli)
        wpa_cli = find_tool("wpa_cli", which, is_file)
        if wpa_cli:
            p = run([wpa_cli, "-i", interface, "ping"], capture_output=True, text=True, timeout=10)
            if "PONG" in (p.stdout or ""):
                return WpaBackend(interface, run=run, tool=wpa_cli)
    except (OSError, subprocess.SubprocessError):
        return None
    return None
