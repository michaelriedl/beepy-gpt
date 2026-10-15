"""Normalized view of `claude agents --json` records."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Optional

REASON_TEXT = {
    "interactive": "interactive session: type /bg in it first",
    "working": "session is working; wait until it stops",
    "unknown_session": "session no longer exists",
    "empty": "nothing to send",
}

# Background states meaning the session has ended; anything else (including an
# unknown or empty state) counts as running, so a reply stops it before resuming.
FINISHED_STATES = frozenset(("done", "stopped", "completed", "failed", "error", "cancelled"))


@dataclass(frozen=True)
class Session:
    id: str
    session_id: str
    kind: str
    name: str
    cwd: str
    state: str
    status: str
    waiting_for: str
    started_at: int
    pid: Optional[int]

    @property
    def project(self) -> str:
        return PurePosixPath(self.cwd).name or self.cwd

    @property
    def needs_you(self) -> bool:
        return self.state == "blocked" or bool(self.waiting_for) or self.status == "waiting"

    @property
    def working(self) -> bool:
        return not self.needs_you and (self.state == "working" or self.status == "working")

    @property
    def running(self) -> bool:
        # Interactive sessions report a pid; background sessions report none (the
        # supervisor owns them), so their state says whether they are still alive.
        if self.pid is not None:
            return True
        return self.kind == "background" and self.state not in FINISHED_STATES


def _s(value: object) -> str:
    return "" if value is None else str(value)


def _int(value: object) -> int:
    try:
        return int(value or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


def from_agents(raw: Iterable[object]) -> list[Session]:
    out = []
    for a in raw:
        if not isinstance(a, dict) or not a.get("sessionId"):
            continue
        sid = str(a["sessionId"])
        pid = a.get("pid")
        out.append(
            Session(
                id=_s(a.get("id")) or sid[:8],
                session_id=sid,
                kind=_s(a.get("kind")) or "interactive",
                name=_s(a.get("name")),
                cwd=_s(a.get("cwd")),
                state=_s(a.get("state")),
                status=_s(a.get("status")),
                waiting_for=_s(a.get("waitingFor")),
                started_at=_int(a.get("startedAt")),
                pid=int(pid) if isinstance(pid, int) else None,
            )
        )
    return out


# `agents --all` also lists finished sessions; keep those started within this window.
RECENT_SECONDS = 86400


def _started_seconds(started_at: int) -> float:
    # Claude Code reports epoch milliseconds; accept seconds too (a value below 1e11
    # would be a date before 1973 in milliseconds, so it must be seconds).
    return started_at / 1000 if started_at >= 1e11 else float(started_at)


def recent(sessions: Iterable[Session], now: Optional[float] = None) -> list[Session]:
    """Sessions with a live process, plus others started in the last RECENT_SECONDS.

    A background session's process exits once it has idled for a while, but its state
    stays as it was (often `blocked` on an old question). Like Claude Code's own views,
    hide those once they are older than RECENT_SECONDS. A session without a start time
    is kept: its age is unknown.
    """
    now = time.time() if now is None else now
    return [
        s for s in sessions
        if s.pid is not None or not s.started_at
        or now - _started_seconds(s.started_at) <= RECENT_SECONDS
    ]


def sort_sessions(sessions: Iterable[Session]) -> list[Session]:
    def key(s: Session) -> tuple[int, int]:
        group = 0 if s.needs_you else 1 if s.working else 2
        return (group, -s.started_at)

    return sorted(sessions, key=key)


def find_session(sessions: Iterable[Session], ident: str) -> Optional[Session]:
    for s in sessions:
        if ident and ident in (s.session_id, s.id):
            return s
    return None


def reply_block_reason(s: Session) -> Optional[str]:
    if s.kind != "background":
        return "interactive"
    if s.state == "working" or s.status == "working":
        return "working"
    return None


def to_wire(s: Session) -> dict:
    return {
        "id": s.id,
        "session_id": s.session_id,
        "kind": s.kind,
        "name": s.name,
        "project": s.project,
        "state": s.state,
        "status": s.status,
        "waiting_for": s.waiting_for,
        "needs_you": s.needs_you,
        "working": s.working,
        "reply_block": reply_block_reason(s),
    }
