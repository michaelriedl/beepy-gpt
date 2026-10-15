"""UI-independent client state and its pure reducer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

MAX_FEED = 500


@dataclass(frozen=True)
class SessionView:
    id: str
    session_id: str
    kind: str
    name: str
    project: str
    state: str
    status: str
    waiting_for: str
    needs_you: bool
    working: bool
    reply_block: Optional[str]

    @staticmethod
    def from_wire(d: dict) -> "SessionView":
        return SessionView(
            id=str(d.get("id", "")), session_id=str(d.get("session_id", "")),
            kind=str(d.get("kind", "")), name=str(d.get("name", "")),
            project=str(d.get("project", "")), state=str(d.get("state", "")),
            status=str(d.get("status", "")), waiting_for=str(d.get("waiting_for", "")),
            needs_you=bool(d.get("needs_you")), working=bool(d.get("working")),
            reply_block=d.get("reply_block"),
        )


@dataclass(frozen=True)
class ApprovalView:
    request_id: str
    session_id: str
    project: str
    session_name: str
    tool_name: str
    tool_input: dict
    description: str
    expires_at: float

    @staticmethod
    def from_wire(d: dict) -> "ApprovalView":
        ti = d.get("tool_input")
        return ApprovalView(
            request_id=str(d.get("request_id", "")), session_id=str(d.get("session_id", "")),
            project=str(d.get("project", "")), session_name=str(d.get("session_name", "")),
            tool_name=str(d.get("tool_name", "")), tool_input=ti if isinstance(ti, dict) else {},
            description=str(d.get("description", "")), expires_at=float(d.get("expires_at") or 0),
        )


@dataclass(frozen=True)
class FeedLine:
    kind: str
    text: str
    ok: Optional[bool] = None

    @staticmethod
    def from_wire(d: dict) -> "FeedLine":
        return FeedLine(str(d.get("kind", "unknown")), str(d.get("text", "")), d.get("ok"))


@dataclass(frozen=True)
class BatteryView:
    percent: int
    charging: bool
    low: bool


@dataclass(frozen=True)
class AppState:
    connection: str = "connecting"
    sessions: tuple = ()
    approvals: tuple = ()
    feed_session: Optional[str] = None
    feed: tuple = ()
    battery: Optional[BatteryView] = None
    wifi: Any = None
    networks: tuple = ()
    wifi_busy: bool = False
    wifi_error: Optional[str] = None
    connectivity: Any = None
    host_version: str = ""
    claude_version: str = ""
    host_error: Optional[str] = None
    fatal: Optional[str] = None
    notice: Optional[str] = None

    @property
    def stale(self) -> bool:
        return self.connection != "online" and bool(self.sessions)

    @property
    def need_ids(self) -> frozenset:
        ids = {s.session_id for s in self.sessions if s.needs_you}
        return frozenset(ids | {a.session_id for a in self.approvals})

    @property
    def need_count(self) -> int:
        return len(self.need_ids)

    def session(self, session_id: Optional[str]) -> Optional[SessionView]:
        return next((s for s in self.sessions if s.session_id == session_id), None)

    def approval(self, request_id: Optional[str]) -> Optional[ApprovalView]:
        return next((a for a in self.approvals if a.request_id == request_id), None)

    def approval_for_session(self, session_id: Optional[str]) -> Optional[ApprovalView]:
        return next((a for a in self.approvals if a.session_id == session_id), None)


def _lines(events: Any) -> tuple:
    return tuple(FeedLine.from_wire(e) for e in (events or []) if isinstance(e, dict))


def reduce(state: AppState, ev: dict) -> AppState:
    t = ev.get("type")
    if t == "sessions":
        return replace(state, sessions=tuple(SessionView.from_wire(d) for d in ev.get("sessions", [])))
    if t == "approvals":
        return replace(state, approvals=tuple(ApprovalView.from_wire(d) for d in ev.get("approvals", [])))
    if t == "feed":
        return replace(state, feed_session=ev.get("session_id"), feed=_lines(ev.get("events"))[-MAX_FEED:])
    if t == "feed_append":
        if ev.get("session_id") != state.feed_session:
            return state
        return replace(state, feed=(state.feed + _lines(ev.get("events")))[-MAX_FEED:])
    if t == "feed_close":
        return replace(state, feed_session=None, feed=())
    if t == "connection":
        return replace(state, connection=str(ev.get("status", "offline")))
    if t == "hello":
        return replace(state, host_version=str(ev.get("host_version", "")),
                       claude_version=str(ev.get("claude_version", "")),
                       host_error=ev.get("claude_error"))
    if t == "host_error":
        return replace(state, host_error=str(ev.get("message", "")))
    if t == "fatal":
        return replace(state, fatal=str(ev.get("message", "")))
    if t == "battery":
        if ev.get("percent") is None:
            return replace(state, battery=None)
        return replace(state, battery=BatteryView(int(ev["percent"]), bool(ev.get("charging")), bool(ev.get("low"))))
    if t == "wifi_status":
        return replace(state, wifi=ev.get("status"))
    if t == "wifi_networks":
        return replace(state, networks=tuple(ev.get("networks", [])), wifi_busy=False, wifi_error=None)
    if t == "wifi_busy":
        return replace(state, wifi_busy=True, wifi_error=None)
    if t == "wifi_error":
        return replace(state, wifi_busy=False, wifi_error=str(ev.get("message", "")))
    if t == "connectivity":
        return replace(state, connectivity=ev.get("result"), wifi_busy=False)
    if t == "notice":
        return replace(state, notice=ev.get("text"))
    return state
