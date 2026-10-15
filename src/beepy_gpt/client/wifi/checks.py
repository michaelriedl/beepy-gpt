"""After joining a network: IP? internet? captive portal? tailscale?"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional

from beepy_gpt.client.wifi import WifiStatus

CHECK_HOST = "connectivitycheck.gstatic.com"
CHECK_PATH = "/generate_204"
CHECK_URL = f"http://{CHECK_HOST}{CHECK_PATH}"


@dataclass(frozen=True)
class Connectivity:
    ip: Optional[str]
    internet: bool
    captive_url: Optional[str]
    tailscale: Optional[bool]


def _default_conn() -> Any:
    return http.client.HTTPConnection(CHECK_HOST, 80, timeout=5)


def check_internet(conn_factory: Callable[[], Any] = _default_conn) -> tuple[bool, Optional[str]]:
    try:
        conn = conn_factory()
        conn.request("GET", CHECK_PATH, headers={"User-Agent": "beepy-gpt"})
        resp = conn.getresponse()
        resp.read(512)
        conn.close()
    except (OSError, http.client.HTTPException):
        return False, None
    if resp.status == 204:
        return True, None
    if resp.status in (301, 302, 303, 307, 308):
        return False, resp.getheader("Location") or CHECK_URL
    return False, CHECK_URL


def check_tailscale(
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[bool]:
    if not which("tailscale"):
        return None
    try:
        p = run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10)
        return p.returncode == 0 and json.loads(p.stdout).get("BackendState") == "Running"
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return False


def run_checks(
    status: WifiStatus,
    internet: Callable[[], tuple[bool, Optional[str]]] = check_internet,
    tailscale: Callable[[], Optional[bool]] = check_tailscale,
) -> Connectivity:
    if not status.ip:
        return Connectivity(None, False, None, tailscale())
    ok, captive = internet()
    return Connectivity(status.ip, ok, captive, tailscale())
