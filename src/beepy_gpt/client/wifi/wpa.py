"""wpa_supplicant backend (wpa_cli), used by Raspberry Pi OS Bullseye."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any, Callable, Optional

from beepy_gpt.client.wifi import Network, WifiError, WifiStatus, sort_networks

log = logging.getLogger(__name__)

_SIMPLE_ESCAPES = {"\\": 0x5C, '"': 0x22, "e": 0x1B, "n": 0x0A, "r": 0x0D, "t": 0x09}
_HEX = "0123456789abcdefABCDEF"


def dbm_to_percent(dbm: int) -> int:
    return max(0, min(100, 2 * (dbm + 100)))


def _unescape(s: str) -> str:
    """Decode wpa_cli's printf-style escaping of an SSID.

    An all-NUL SSID is a cloaked AP and decodes to "".
    """
    out = bytearray()
    i = 0
    while i < len(s):
        ch = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        hx = s[i + 2:i + 4]
        if ch == "\\" and nxt == "x" and len(hx) == 2 and all(c in _HEX for c in hx):
            out.append(int(hx, 16))
            i += 4
        elif ch == "\\" and nxt in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[nxt])
            i += 2
        else:
            out.extend(ch.encode("utf-8"))
            i += 1
    if not out.strip(b"\x00"):
        return ""
    return out.decode("utf-8", errors="replace")


def _kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class WpaBackend:
    name = "wpa_supplicant"

    def __init__(
        self,
        interface: str = "wlan0",
        run: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        connect_timeout: float = 20.0,
    ):
        self.interface = interface
        self._run = run
        self._sleep = sleep
        self._connect_timeout = connect_timeout

    def _w(self, *args: str) -> str:
        try:
            p = self._run(["wpa_cli", "-i", self.interface, *args], capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise WifiError("timeout", "wpa_cli timed out") from None
        except OSError as e:
            raise WifiError("backend", f"cannot run wpa_cli: {e.strerror}") from None
        out = (p.stdout or "") + (p.stderr or "")
        if "permission denied" in out.lower():
            raise WifiError("permission", "wpa_cli: permission denied")
        if p.returncode != 0 or out.strip() == "FAIL":
            # Never echo arguments or output: they may contain the password.
            raise WifiError("backend", f"wpa_cli {args[0]} failed")
        return p.stdout or ""

    def _networks(self) -> list[tuple[str, str, bool]]:
        rows = []
        for line in self._w("list_networks").splitlines()[1:]:
            f = line.split("\t")
            if len(f) >= 2:
                rows.append((f[0], _unescape(f[1]), "[CURRENT]" in (f[3] if len(f) > 3 else "")))
        return rows

    def _status(self) -> dict:
        st = _kv(self._w("status"))
        if "ssid" in st:
            st["ssid"] = _unescape(st["ssid"])
        return st

    def scan(self) -> list[Network]:
        self._w("scan")
        self._sleep(3)
        results = self._w("scan_results")
        saved = {ssid for _, ssid, _ in self._networks()}
        active = self._status().get("ssid")
        nets = []
        for line in results.splitlines()[1:]:
            f = line.split("\t")
            if len(f) < 5:
                continue
            ssid = _unescape(f[4])
            if not ssid:
                continue
            try:
                dbm = int(f[2])
            except ValueError:
                continue
            secure = any(x in f[3] for x in ("WPA", "WEP", "RSN"))
            nets.append(Network(ssid, dbm_to_percent(dbm), secure, ssid in saved, ssid == active))
        return sort_networks(nets)

    def status(self) -> WifiStatus:
        st = self._status()
        if st.get("wpa_state") != "COMPLETED":
            return WifiStatus()
        rssi = _kv(self._w("signal_poll")).get("RSSI")
        signal = dbm_to_percent(int(rssi)) if rssi and rssi.lstrip("-").isdigit() else None
        return WifiStatus(st.get("ssid"), signal, st.get("ip_address"))

    def _wait_connected(self, ssid: str) -> bool:
        deadline = self._connect_timeout
        waited = 0.0
        while waited <= deadline:
            st = self._status()
            if st.get("wpa_state") == "COMPLETED" and st.get("ssid") == ssid:
                return True
            self._sleep(1)
            waited += 1
        return False

    def _enable_all(self) -> None:
        # select_network disables every other network in wpa_supplicant; undo that.
        try:
            self._w("enable_network", "all")
        except WifiError:
            log.warning("could not re-enable the other saved Wi-Fi networks")

    def _save(self) -> None:
        # save_config only works with update_config=1; without it the change lasts until reboot.
        try:
            self._w("save_config")
        except WifiError:
            log.warning("wpa_cli save_config failed; Wi-Fi changes will not survive a reboot")

    def connect(self, ssid: str, password: Optional[str] = None, hidden: bool = False) -> None:
        # Redact outside the except block so __context__ never holds the unredacted error.
        try:
            self._connect(ssid, password, hidden)
            return
        except WifiError as e:
            code, message = e.code, e.message
        if password:
            message = message.replace(password, "***")
        raise WifiError(code, message)

    def _connect(self, ssid: str, password: Optional[str], hidden: bool) -> None:
        if password is not None and not 8 <= len(password) <= 63:
            raise WifiError("auth_failed", "Wi-Fi passwords are 8 to 63 characters")
        existing = next((nid for nid, s, _ in self._networks() if s == ssid), None)
        if existing is not None and password is None:
            self._w("select_network", existing)
            if not self._wait_connected(ssid):
                self._enable_all()
                raise WifiError("auth_failed", f"could not join {ssid}")
            self._enable_all()
            return
        nid = self._w("add_network").strip().splitlines()[-1]
        try:
            self._w("set_network", nid, "ssid", ssid.encode("utf-8").hex())
            if password:
                self._w("set_network", nid, "psk", f'"{password}"')
            else:
                self._w("set_network", nid, "key_mgmt", "NONE")
            if hidden:
                self._w("set_network", nid, "scan_ssid", "1")
            self._w("enable_network", nid)
            self._w("select_network", nid)
            if not self._wait_connected(ssid):
                raise WifiError("auth_failed", f"could not join {ssid} (wrong password?)")
        except WifiError:
            try:
                self._w("remove_network", nid)
            except WifiError:
                pass
            self._enable_all()
            raise
        self._enable_all()
        self._save()

    def forget(self, ssid: str) -> None:
        for nid, s, _ in self._networks():
            if s == ssid:
                self._w("remove_network", nid)
        self._enable_all()
        self._save()
