"""Shared test helpers. Paths and names here are made up — never use real ones."""

from __future__ import annotations


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
