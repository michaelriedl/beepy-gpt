"""Normalized view of `claude agents --json` records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Optional

REASON_TEXT = {
    "interactive": "interactive session: type /bg in it first",
    "working": "session is working; wait until it stops",
    "unknown_session": "session no longer exists",
    "empty": "nothing to send",
}


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
        return self.pid is not None


def _s(value: object) -> str:
    return "" if value is None else str(value)


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
                started_at=int(a.get("startedAt") or 0),
                pid=int(pid) if isinstance(pid, int) else None,
            )
        )
    return out


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
    if s.working:
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
