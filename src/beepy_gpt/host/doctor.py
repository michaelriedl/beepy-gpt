"""`bgpt-host doctor`: self-checks for the workstation side."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from beepy_gpt.config import HostConfig
from beepy_gpt.host.claude_cli import ClaudeError
from beepy_gpt.host.install import hook_installed, load_settings


def run_doctor(cli: Any, cfg: HostConfig, settings_path: Path, out: Callable[[str], None]) -> int:
    checks = []
    try:
        checks.append((True, "claude", cli.version()))
    except ClaudeError as e:
        checks.append((False, "claude", str(e)))
    try:
        checks.append((True, "claude agents --json", f"{len(cli.agents())} active session(s)"))
    except ClaudeError as e:
        checks.append((False, "claude agents --json", str(e)))
    try:
        installed = hook_installed(load_settings(settings_path))
        detail = "installed" if installed else "not installed: run `bgpt-host install-hook`"
        checks.append((installed, "PermissionRequest hook", detail))
    except ValueError as e:
        checks.append((False, "PermissionRequest hook", f"cannot read {settings_path}: {e}"))
    spool = cfg.state_dir / "approvals"
    try:
        spool.mkdir(parents=True, exist_ok=True)
        probe = spool / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append((True, "approval spool", str(spool)))
    except OSError as e:
        checks.append((False, "approval spool", f"{spool}: {e}"))
    for ok, name, detail in checks:
        out(f"[{'ok' if ok else '!!'}] {name}: {detail}")
    return 0 if all(ok for ok, _, _ in checks) else 1
