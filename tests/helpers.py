"""Shared test helpers. Paths and names here are made up — never use real ones."""

from __future__ import annotations

import subprocess

def agent(
    id="aaaa1111",
    kind="background",
    state="blocked",
    status="waiting",
    waitingFor="permission prompt",
    pid=101,
    cwd="/home/dev/proj",
    name="demo",
    startedAt=1000,
):
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
