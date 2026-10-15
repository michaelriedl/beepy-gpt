"""`bgpt-host serve`: JSON-lines loop over stdio; the host polls, the client is pushed."""

from __future__ import annotations

import os
import select
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from beepy_gpt import __version__
from beepy_gpt.host.actions import ActionError, reply
from beepy_gpt.host.approvals import ApprovalRequest, Spool, SpoolError
from beepy_gpt.host.claude_cli import ClaudeError
from beepy_gpt.host.sessions import REASON_TEXT, Session, find_session, from_agents, sort_sessions, to_wire
from beepy_gpt.host.transcripts import read_events, set_claude_version
from beepy_gpt.protocol import PROTOCOL_VERSION, ProtocolError, decode, encode, response_error, response_ok

FEED_TAIL = 200


class Server:
    def __init__(
        self,
        backend: Any,
        spool: Spool,
        out: Callable[[dict], None],
        transcript_for: Callable[[Session], Path],
        poll_seconds: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.backend = backend
        self.spool = spool
        self.out = out
        self.transcript_for = transcript_for
        self.poll_seconds = poll_seconds
        self.clock = clock
        self._hello = False
        self._sessions: list[Session] = []
        self._sessions_wire: Optional[list] = None
        self._approvals_wire: Optional[list] = None
        self._feed: Optional[tuple[str, Path, int]] = None
        self._last_poll = float("-inf")
        self._last_error: Optional[str] = None
        self._last_tick_error: Optional[str] = None

    # --- requests -------------------------------------------------------
    def handle(self, msg: dict) -> None:
        rid = msg.get("id")
        mtype = msg.get("type")
        if mtype == "hello":
            self._on_hello(msg, rid)
            return
        if not self._hello:
            self.out(response_error(rid, "no_hello", "send hello first"))
            return
        handler = {
            "feed": self._on_feed,
            "close_feed": self._on_close_feed,
            "reply": self._on_reply,
            "decide": self._on_decide,
            "refresh": self._on_refresh,
        }.get(str(mtype))
        if handler is None:
            self.out(response_error(rid, "unknown_type", f"unknown message type {mtype!r}"))
            return
        try:
            handler(msg, rid)
        except (ActionError, SpoolError) as e:
            self.out(response_error(rid, e.code, str(e)))
        except ClaudeError as e:
            self.out(response_error(rid, "claude_error", str(e)))
            return
        except Exception as e:  # one bad request must never kill the server
            self.out(response_error(rid, "internal", f"{type(e).__name__}: {e}"))
            return
        if mtype in ("reply", "decide", "refresh"):
            self.tick(force=True)

    def _on_hello(self, msg: dict, rid: Any) -> None:
        if msg.get("v") != PROTOCOL_VERSION:
            self.out(response_error(
                rid, "protocol_mismatch",
                f"client protocol {msg.get('v')}, host protocol {PROTOCOL_VERSION}",
            ))
            return
        try:
            claude_version, claude_error = self.backend.version(), None
        except ClaudeError as e:
            claude_version, claude_error = "", str(e)
        set_claude_version(claude_version)
        self._hello = True
        self.out(response_ok(
            rid, host_version=__version__, protocol=PROTOCOL_VERSION,
            claude_version=claude_version, claude_error=claude_error,
        ))
        self._sessions_wire = None
        self._approvals_wire = None
        self.tick(force=True)

    def _on_feed(self, msg: dict, rid: Any) -> None:
        sessions = self._sessions or from_agents(self.backend.agents())
        s = find_session(sessions, str(msg.get("session_id", "")))
        if s is None:
            raise ActionError("unknown_session", REASON_TEXT["unknown_session"])
        path = self.transcript_for(s)
        events, offset = read_events(path, 0)
        self._feed = (s.session_id, path, offset)
        self.out(response_ok(rid, session_id=s.session_id, events=[e.to_wire() for e in events[-FEED_TAIL:]]))

    def _on_close_feed(self, msg: dict, rid: Any) -> None:
        self._feed = None
        self.out(response_ok(rid))

    def _on_reply(self, msg: dict, rid: Any) -> None:
        result = reply(self.backend, str(msg.get("session_id", "")), str(msg.get("text", "")))
        self.out(response_ok(rid, **result))

    def _on_decide(self, msg: dict, rid: Any) -> None:
        self.spool.decide(str(msg.get("request_id", "")), str(msg.get("behavior", "")), str(msg.get("message", "")))
        self.out(response_ok(rid))

    def _on_refresh(self, msg: dict, rid: Any) -> None:
        self.out(response_ok(rid))

    # --- pushes ---------------------------------------------------------
    def _approval_wire(self, r: ApprovalRequest) -> dict:
        s = find_session(self._sessions, r.session_id)
        d = r.to_wire()
        d["project"] = s.project if s else (PurePosixPath(r.cwd).name or r.cwd)
        d["session_name"] = s.name if s else ""
        return d

    def tick(self, force: bool = False) -> None:
        try:
            self._tick(force)
        except Exception as e:  # e.g. unreadable transcript or spool; report once, keep serving
            msg = f"{type(e).__name__}: {e}"
            if msg != self._last_tick_error:
                self._last_tick_error = msg
                self.out({"type": "host_error", "message": msg})
        else:
            self._last_tick_error = None

    def _tick(self, force: bool) -> None:
        if not self._hello:
            return
        now = self.clock()
        if force or now - self._last_poll >= self.poll_seconds:
            self._last_poll = now
            try:
                self._sessions = sort_sessions(from_agents(self.backend.agents()))
                self._last_error = None
            except ClaudeError as e:
                if str(e) != self._last_error:
                    self._last_error = str(e)
                    self.out({"type": "host_error", "message": str(e)})
            wire = [to_wire(s) for s in self._sessions]
            if wire != self._sessions_wire:
                self._sessions_wire = wire
                self.out({"type": "sessions", "sessions": wire})
        approvals = [self._approval_wire(r) for r in self.spool.pending()]
        if approvals != self._approvals_wire:
            self._approvals_wire = approvals
            self.out({"type": "approvals", "approvals": approvals})
        if self._feed:
            sid, path, offset = self._feed
            events, new_offset = read_events(path, offset)
            self._feed = (sid, path, new_offset)
            if events:
                self.out({"type": "feed_append", "session_id": sid, "events": [e.to_wire() for e in events]})


def stdout_writer(stream: Any = sys.stdout) -> Callable[[dict], None]:
    def out(msg: dict) -> None:
        stream.write(encode(msg))
        stream.flush()

    return out


def serve_stdio(
    server: Server, fd_in: int, tick_seconds: float = 1.0, exit_after: Optional[float] = None
) -> None:
    buf = b""
    start = time.monotonic()
    while True:
        if exit_after is not None and time.monotonic() - start >= exit_after:
            return
        ready, _, _ = select.select([fd_in], [], [], tick_seconds)
        if ready:
            chunk = os.read(fd_in, 65536)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = decode(line.decode("utf-8", "replace"))
                except (ProtocolError, RecursionError) as e:
                    server.out(response_error(None, "bad_message", str(e)))
                    continue
                server.handle(msg)
        server.tick()
