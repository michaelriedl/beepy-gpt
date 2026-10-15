"""Scripted Claude backend for `bgpt-host serve --fake` (development and tests)."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Callable

from beepy_gpt.host.approvals import Spool
from beepy_gpt.host.claude_cli import ClaudeError, ResumeResult
from beepy_gpt.host.sessions import Session


def _sid(short: str) -> str:
    return f"{short}-0000-4000-8000-000000000000"


def _rec(short, kind, name, cwd, state, status, waiting, pid, started):
    return {
        "pid": pid, "id": short if kind == "background" else None,
        # epoch ms like the real CLI; `started` only orders the sessions (minutes ago)
        "cwd": cwd, "kind": kind, "startedAt": int(time.time() * 1000) - (10 - started) * 60_000,
        "sessionId": _sid(short), "name": name, "state": state, "status": status,
        "waitingFor": waiting,
    }


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


class FakeClaude:
    def __init__(self, workdir: Path, spool: Spool, clock: Callable[[], float] = time.monotonic):
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._t0 = clock()
        cwds = {}
        for project in ("parser", "orbit", "notes", "fonts", "demo"):
            d = self.workdir / "projects" / project
            d.mkdir(parents=True, exist_ok=True)
            cwds[project] = str(d)
        self._sessions = {
            "aaaa1111": _rec("aaaa1111", "background", "Refactor parser", cwds["parser"], "blocked", "waiting", "permission prompt", 101, 5),
            "bbbb2222": _rec("bbbb2222", "background", "train sweep", cwds["orbit"], "working", None, None, 102, 4),
            "cccc3333": _rec("cccc3333", "interactive", "notes-app-12", cwds["notes"], None, "idle", None, 103, 3),
            "dddd4444": _rec("dddd4444", "background", "fix loader", cwds["fonts"], "done", "idle", None, 104, 2),
            "eeee5555": _rec("eeee5555", "background", "fork demo", cwds["demo"], "blocked", "idle", None, 105, 1),
        }
        for short in self._sessions:
            self._write(short, [
                _user(f"Please work on the {self._sessions[short]['name']} task."),
                _assistant({"type": "text", "text": "Sure. Looking at the code first, then I will run the tests and report back with a summary of what changed."}),
                _assistant({"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}),
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "12 passed in 1.02s"}]}},
            ])
        spool.create({
            "session_id": _sid("aaaa1111"), "cwd": cwds["parser"],
            "hook_event_name": "PermissionRequest", "tool_name": "Bash",
            "tool_input": {
                "command": "python -m pytest tests/test_parser.py --maxfail=1 -k 'tokenize or parse_header'",
                "description": "Run the parser tests",
            },
        }, timeout=3600)

    def _path(self, short: str) -> Path:
        return self.workdir / f"{_sid(short)}.jsonl"

    def _write(self, short: str, entries: list) -> None:
        with self._path(short).open("a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _find(self, ident: str) -> dict:
        for short, rec in self._sessions.items():
            if ident in (short, rec["sessionId"]):
                return rec
        raise ClaudeError(f"no session {ident}")

    def agents(self, include_all: bool = False) -> list:
        if self._clock() - self._t0 >= 20:
            self._sessions["bbbb2222"].update(state="done", status="idle")
        return [{k: v for k, v in r.items() if v is not None} for r in copy.deepcopy(list(self._sessions.values()))]

    def stop(self, short_id: str) -> None:
        self._find(short_id).update(pid=None, state="stopped", status=None, waitingFor=None)

    def resume_bg(self, session_id: str, text: str, cwd: str) -> ResumeResult:
        rec = self._find(session_id)
        short = rec["sessionId"][:8]
        if short == "eeee5555":
            return ResumeResult(short_id="f0f0f0f0", forked_as="f0f0f0f0")
        self._write(short, [_user(text.strip()), _assistant({"type": "text", "text": f"(fake) received: {text.strip()}"})])
        rec.update(pid=4242, state="done", status="idle", waitingFor=None)
        return ResumeResult(short_id=short, forked_as=None)

    def version(self) -> str:
        return "fake (Claude Code)"

    def transcript_for(self, session: Session) -> Path:
        return self.workdir / f"{session.session_id}.jsonl"
