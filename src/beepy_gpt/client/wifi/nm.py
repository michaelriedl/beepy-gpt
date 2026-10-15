"""NetworkManager backend (nmcli), the default on Raspberry Pi OS Bookworm."""

from __future__ import annotations

import os
import subprocess
from typing import Any, Callable, Optional

from beepy_gpt.client.wifi import Network, WifiError, WifiStatus, sort_networks


def split_terse(line: str) -> list[str]:
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def _error(text: str) -> WifiError:
    low = text.lower()
    if "not authorized" in low or "insufficient privileges" in low or "permission denied" in low:
        code = "permission"
    elif "secrets were required" in low or "invalid password" in low or "802-11-wireless-security" in low:
        code = "auth_failed"
    elif "no network with ssid" in low:
        code = "not_found"
    else:
        code = "backend"
    lines = text.strip().splitlines()
    return WifiError(code, lines[-1] if lines else "nmcli failed")


def _int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return 0


class NmBackend:
    name = "networkmanager"

    def __init__(self, interface: str = "wlan0", run: Callable[..., Any] = subprocess.run):
        self.interface = interface
        self._run = run

    def _nm(self, *args: str, timeout: float = 30) -> str:
        try:
            p = self._run(["nmcli", *args], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "LC_ALL": "C"})
        except subprocess.TimeoutExpired:
            raise WifiError("timeout", "nmcli timed out") from None
        except OSError as e:
            raise WifiError("backend", f"cannot run nmcli: {e.strerror}") from None
        if p.returncode != 0:
            raise _error(p.stderr or p.stdout or "")
        return p.stdout or ""

    def _saved(self) -> set:
        out = self._nm("-t", "-f", "NAME,TYPE", "connection", "show")
        return {f[0] for f in map(split_terse, out.splitlines()) if len(f) >= 2 and f[1] in ("802-11-wireless", "wifi")}

    def scan(self) -> list[Network]:
        out = self._nm("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                       "ifname", self.interface, "--rescan", "yes", timeout=45)
        saved = self._saved()
        nets = []
        for f in map(split_terse, out.splitlines()):
            if len(f) < 4:
                continue
            in_use, ssid, signal, security = f[0].strip(), f[1], f[2], f[3].strip()
            nets.append(Network(ssid, _int(signal), security not in ("", "--"), ssid in saved, in_use == "*"))
        return sort_networks(nets)

    def status(self) -> WifiStatus:
        out = self._nm("-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list",
                       "ifname", self.interface, "--rescan", "no")
        ssid = signal = None
        for f in map(split_terse, out.splitlines()):
            if len(f) >= 3 and f[0].strip() == "*":
                ssid, signal = f[1], _int(f[2])
        ip_out = self._nm("-t", "-g", "IP4.ADDRESS", "device", "show", self.interface)
        first = ip_out.strip().split("|")[0].split("/")[0] if ip_out.strip() else ""
        return WifiStatus(ssid, signal, first or None)

    def connect(self, ssid: str, password: Optional[str] = None, hidden: bool = False) -> None:
        # Task 25 checks whether nmcli can take the password from a file instead of
        # argv; until then it is passed as an argument and never logged.
        args = ["device", "wifi", "connect", ssid, "ifname", self.interface]
        if password:
            args += ["password", password]
        if hidden:
            args += ["hidden", "yes"]
        try:
            self._nm(*args, timeout=90)
        except WifiError as e:
            # nmcli can echo argv values back in its errors; never let the password through.
            if password:
                raise WifiError(e.code, e.message.replace(password, "***")) from None
            raise

    def forget(self, ssid: str) -> None:
        self._nm("connection", "delete", "id", ssid)
