"""Scripted Wi-Fi backend for the emulator and tests."""

from __future__ import annotations

from typing import Optional

from beepy_gpt.client.wifi import Network, WifiError, WifiStatus, sort_networks
from beepy_gpt.client.wifi.checks import Connectivity

DROPOUT_SSID = "Weak Signal"


class FakeWifi:
    name = "fake"

    def __init__(self):
        self._nets = {
            "HomeNet": Network("HomeNet", 82, True, saved=True, active=True),
            "CoffeeShop": Network("CoffeeShop", 61, True),
            "Airport_Free": Network("Airport_Free", 45, False),
            "Weak Signal": Network("Weak Signal", 10, True),
        }

    def scan(self) -> list[Network]:
        return sort_networks(list(self._nets.values()))

    def status(self) -> WifiStatus:
        active = next((n for n in self._nets.values() if n.active), None)
        if active is not None and active.ssid == DROPOUT_SSID:
            # Scripted dropout: the weak link falls over right after joining.
            self._nets[active.ssid] = Network(active.ssid, active.signal, active.secure, active.saved, False)
            return WifiStatus()
        return WifiStatus(active.ssid, active.signal, "192.168.4.20") if active else WifiStatus()

    def connect(self, ssid: str, password: Optional[str] = None, hidden: bool = False) -> None:
        net = self._nets.get(ssid) or Network(ssid, 50, password is not None)
        if net.secure and not net.saved and not password:
            raise WifiError("auth_failed", "password required")
        if password == "wrongpass":
            raise WifiError("auth_failed", f"could not join {ssid} (wrong password?)")
        self._nets = {k: Network(n.ssid, n.signal, n.secure, n.saved, False) for k, n in self._nets.items()}
        self._nets[ssid] = Network(ssid, net.signal, net.secure, True, True)

    def forget(self, ssid: str) -> None:
        n = self._nets.get(ssid)
        if n:
            self._nets[ssid] = Network(n.ssid, n.signal, n.secure, False, False)

    def checks(self, status: WifiStatus) -> Connectivity:
        captive = status.ssid == "Airport_Free"
        return Connectivity(
            status.ip, bool(status.ip) and not captive,
            "http://portal.example/login" if captive else None, bool(status.ip) and not captive,
        )
