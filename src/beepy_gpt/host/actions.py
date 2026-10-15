"""Write actions on sessions, with host-enforced guard rules (spec §5.1)."""

from __future__ import annotations

from typing import Any

from beepy_gpt.host.claude_cli import ClaudeError
from beepy_gpt.host.sessions import REASON_TEXT, find_session, from_agents, reply_block_reason


class ActionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _err(code: str) -> ActionError:
    return ActionError(code, REASON_TEXT[code])


def prepare_text(text: str) -> str:
    body = text.strip()
    if not body:
        raise _err("empty")
    # A leading "-" would be parsed as a CLI flag; a leading space keeps it positional.
    return " " + body if body.startswith("-") else body


def _lookup(backend: Any, ident: str):
    s = find_session(from_agents(backend.agents()), ident)
    if s is None:
        raise _err("unknown_session")
    reason = reply_block_reason(s)
    if reason:
        raise _err(reason)
    return s


def reply(backend: Any, ident: str, text: str) -> dict:
    body = prepare_text(text)
    try:
        s = _lookup(backend, ident)
        if s.running:
            # Re-check right before stopping so a session that just started working
            # is never interrupted.
            s = _lookup(backend, s.session_id)
            backend.stop(s.id)
        result = backend.resume_bg(s.session_id, body, cwd=s.cwd)
    except ClaudeError as e:
        raise ActionError("claude_error", str(e)) from None
    return {"forked_as": result.forked_as}
