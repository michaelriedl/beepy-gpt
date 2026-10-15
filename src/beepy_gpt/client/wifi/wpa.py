"""wpa_supplicant backend (wpa_cli). Implemented in Task 15."""

from __future__ import annotations


class WpaBackend:
    name = "wpa_supplicant"

    def __init__(self, interface: str = "wlan0", run=None):
        self.interface = interface
        self._run = run
