"""`bgpt doctor`: client-side self-checks."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Callable

from beepy_gpt.client.transport import ssh_argv


def run_client_doctor(
    cfg: Any,
    out: Callable[[str], None],
    run: Callable[..., Any] = subprocess.run,
    device: Any = None,
    wifi: Any = None,
    term_size: Callable[[], Any] = shutil.get_terminal_size,
) -> int:
    checks = []
    if not cfg.ssh_target:
        checks.append((False, "config", "set [host] ssh_target in ~/.config/beepy-gpt/client.ini"))
    else:
        argv = ssh_argv(cfg.ssh_target, cfg.ssh_options, cfg.host_command)[:-1] + ["--version"]
        try:
            p = run(argv, capture_output=True, text=True, timeout=20)
            ok = p.returncode == 0 and p.stdout.startswith("bgpt-host")
            text = (p.stderr or p.stdout or "").strip()
            detail = p.stdout.strip() if ok else (text.splitlines()[-1] if text else "no output")
        except (OSError, subprocess.SubprocessError) as e:
            ok, detail = False, str(e)
        checks.append((ok, "host", detail))
    if device is not None and device.available:
        reading = device.read_battery()
        checks.append((reading is not None, "battery", f"{reading[0]}% {reading[1]:.2f}V" if reading else "unreadable"))
    else:
        checks.append((True, "battery", "no Beepy firmware found (battery display hidden)"))
    checks.append((True, "wifi", f"backend: {wifi.name}" if wifi else "no supported Wi-Fi backend (menu disabled)"))
    size = term_size()
    big = size.columns >= 50 and size.lines >= 30
    checks.append((big, "terminal", f"{size.columns}x{size.lines}" + ("" if big else " (need at least 50x30)")))
    for ok, name, detail in checks:
        out(f"[{'ok' if ok else '!!'}] {name}: {detail}")
    return 0 if all(ok for ok, _, _ in checks) else 1
