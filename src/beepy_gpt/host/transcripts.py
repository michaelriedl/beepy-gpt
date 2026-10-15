"""The only parser of Claude Code transcript JSONL (an internal, version-dependent format)."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
_warned: set = set()
_SKIP_BLOCKS = {"thinking", "redacted_thinking", "image"}
_TOOL_KEYS = ("file_path", "path", "pattern", "url", "query", "description")
_MAX = 200
_claude_version = "unknown"


def set_claude_version(version: str) -> None:
    """Record the Claude Code version so format warnings can name it (spec §5.4)."""
    global _claude_version
    _claude_version = version or "unknown"


@dataclass(frozen=True)
class FeedEvent:
    kind: str
    text: str
    ok: Optional[bool] = None

    def to_wire(self) -> dict:
        return {"kind": self.kind, "text": self.text, "ok": self.ok}


def _warn_once(what: str) -> None:
    if what not in _warned:
        _warned.add(what)
        log.warning("transcript: skipping unrecognized %s (Claude Code %s)", what, _claude_version)


def summarize_tool(name: str, tool_input: dict) -> str:
    if name == "Bash":
        lines = str(tool_input.get("command", "")).splitlines() or [""]
        text = "$ " + lines[0] + (" …" if len(lines) > 1 else "")
    else:
        detail = next((str(tool_input[k]) for k in _TOOL_KEYS if tool_input.get(k)), "")
        text = f"{name} {detail}".strip()
    return text[:_MAX]


def _result(block: dict) -> FeedEvent:
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    text = str(content or "")
    if text.startswith("[Tool call interrupted"):
        return FeedEvent("interrupted", "interrupted")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "(no output)")
    return FeedEvent("tool_result", first[:_MAX], not bool(block.get("is_error")))


def parse_entry(entry: dict) -> list[FeedEvent]:
    etype = entry.get("type")
    if etype not in ("user", "assistant"):
        _warn_once(f"entry type {etype!r}")
        return []
    speaker = "you" if etype == "user" else "claude"
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        text = content.strip()
        return [FeedEvent(speaker, text)] if text else []
    if not isinstance(content, list):
        return [FeedEvent("unknown", f"{etype} entry")]
    events = []
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else None
        if btype == "text":
            text = str(block.get("text") or "").strip()
            if text:
                events.append(FeedEvent(speaker, text))
        elif btype == "tool_use":
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            events.append(FeedEvent("tool_call", summarize_tool(str(block.get("name", "")), tool_input)))
        elif btype == "tool_result":
            events.append(_result(block))
        elif btype in _SKIP_BLOCKS:
            continue
        else:
            _warn_once(f"content block {btype!r}")
            events.append(FeedEvent("unknown", str(btype)))
    return events


def read_events(path: Path, offset: int = 0) -> tuple[list[FeedEvent], int]:
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size < offset:
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return [], offset
    events: list[FeedEvent] = []
    for raw in data[: end + 1].splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            events.append(FeedEvent("unknown", "unreadable line"))
            continue
        if isinstance(entry, dict):
            events.extend(parse_entry(entry))
    return events, offset + end + 1


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def transcript_path(home: Path, cwd: str, session_id: str) -> Path:
    return home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", cwd) / f"{session_id}.jsonl"
