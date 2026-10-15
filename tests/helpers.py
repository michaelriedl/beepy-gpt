"""Shared test helpers. Paths and names here are made up — never use real ones."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


def agent(
    id="aaaa1111",
    kind="background",
    state="blocked",
    status="waiting",
    waitingFor="permission prompt",
    pid="auto",
    cwd="/home/dev/proj",
    name="demo",
    startedAt="now",
):
    if pid == "auto":  # like Claude Code: only interactive sessions report a pid
        pid = None if kind == "background" else 101
    if startedAt == "now":  # epoch milliseconds, recent enough to pass the 24 h filter
        startedAt = int(time.time() * 1000)
    rec = {
        "pid": pid,
        "id": id if kind == "background" else None,
        "cwd": cwd,
        "kind": kind,
        "startedAt": startedAt,
        "sessionId": f"{id}-0000-4000-8000-000000000000",
        "name": name,
        "state": state,
        "status": status,
        "waitingFor": waitingFor,
    }
    return {k: v for k, v in rec.items() if v is not None}


class FakeRun:
    """Stands in for subprocess.run: answers by argv prefix, records every call."""

    def __init__(self):
        self.calls = []
        self.envs = []
        self.rules = []

    def on(self, prefix, stdout="", returncode=0, stderr=""):
        self.rules.append((list(prefix), returncode, stdout, stderr))

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        self.envs.append(kwargs.get("env"))
        for prefix, rc, out, err in reversed(self.rules):
            if argv[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(argv, rc, out, err)
        return subprocess.CompletedProcess(argv, 1, "", f"FakeRun: unexpected {argv}")


def assert_golden(name, grid):
    import pytest

    path = GOLDEN / f"{name}.txt"
    snap = grid.snapshot()
    if os.environ.get("BGPT_UPDATE_GOLDEN") or not path.exists():
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(snap, encoding="utf-8")
        if not os.environ.get("BGPT_UPDATE_GOLDEN"):
            pytest.fail(f"golden {name} created at {path}; review it, then re-run")
    assert snap == path.read_text(encoding="utf-8"), f"screen {name} changed; diff against {path}"
