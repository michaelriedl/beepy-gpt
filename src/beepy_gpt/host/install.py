"""Install / remove the bgpt PermissionRequest hook in Claude Code user settings."""

from __future__ import annotations

import copy
import difflib
import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from beepy_gpt.host.transcripts import claude_home


def default_settings_path() -> Path:
    return claude_home() / "settings.json"


_MARKERS = ("bgpt-host", "beepy_gpt.host.cli")


def hook_command() -> str:
    exe = shutil.which("bgpt-host")
    if exe:
        return f"{shlex.quote(str(Path(exe).resolve()))} hook"
    return f"{shlex.quote(sys.executable)} -m beepy_gpt.host.cli hook"


def is_our_hook(h: object) -> bool:
    if not isinstance(h, dict) or h.get("type") != "command":
        return False
    cmd = str(h.get("command", ""))
    return any(m in cmd for m in _MARKERS) and cmd.split()[-1:] == ["hook"]


def _groups(settings: dict) -> list:
    hooks = settings.get("hooks")
    groups = hooks.get("PermissionRequest") if isinstance(hooks, dict) else None
    return groups if isinstance(groups, list) else []


def hook_installed(settings: dict) -> bool:
    return any(is_our_hook(h) for g in _groups(settings) if isinstance(g, dict) for h in g.get("hooks", []))


def plan_install(settings: dict, command: str, timeout: int) -> dict:
    new = copy.deepcopy(settings)
    groups = new.setdefault("hooks", {}).setdefault("PermissionRequest", [])
    for g in groups:
        for h in g.get("hooks", []) if isinstance(g, dict) else []:
            if is_our_hook(h):
                h["command"] = command
                h["timeout"] = timeout
                return new
    groups.append({"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": timeout}]})
    return new


def plan_uninstall(settings: dict) -> dict:
    new = copy.deepcopy(settings)
    hooks = new.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("PermissionRequest"), list):
        return new
    kept = []
    for g in hooks["PermissionRequest"]:
        if isinstance(g, dict) and isinstance(g.get("hooks"), list):
            g["hooks"] = [h for h in g["hooks"] if not is_our_hook(h)]
            if not g["hooks"]:
                continue
        kept.append(g)
    if kept:
        hooks["PermissionRequest"] = kept
    else:
        del hooks["PermissionRequest"]
    if not hooks:
        del new["hooks"]
    return new


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _dump(d: dict) -> str:
    return json.dumps(d, indent=2) + "\n"


def render_diff(old: dict, new: dict, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            _dump(old).splitlines(True), _dump(new).splitlines(True), str(path), f"{path} (new)"
        )
    )


def write_settings(path: Path, new: dict) -> Optional[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.bgpt-backup-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup)
    tmp = path.with_name(f".{path.name}.bgpt-tmp")
    tmp.write_text(_dump(new), encoding="utf-8")
    os.replace(tmp, path)
    return backup


def run_change(
    path: Path,
    change: Callable[[dict], dict],
    confirm: Callable[[str], bool],
    out: Callable[[str], None],
) -> int:
    try:
        old = load_settings(path)
    except ValueError as e:
        out(f"cannot read {path}: {e}")
        return 1
    new = change(old)
    if new == old:
        out(f"{path}: already up to date, nothing to do")
        return 0
    diff = render_diff(old, new, path)
    out(diff)
    if not confirm(diff):
        out("no changes written")
        return 0
    backup = write_settings(path, new)
    out(f"wrote {path}" + (f" (backup: {backup})" if backup else ""))
    return 0
