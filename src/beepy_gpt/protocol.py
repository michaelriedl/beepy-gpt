"""JSON-lines wire protocol shared by bgpt (client) and bgpt-host (host)."""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    """A line that is not a valid protocol message."""


def encode(msg: dict[str, Any]) -> str:
    if "type" not in msg:
        raise ProtocolError("message has no type")
    out = {**msg, "v": PROTOCOL_VERSION}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n"


def decode(line: str) -> dict[str, Any]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"bad json: {e}") from None
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise ProtocolError("message must be a JSON object with a string 'type'")
    return msg


def response_ok(req_id: Any, **fields: Any) -> dict[str, Any]:
    return {"type": "response", "id": req_id, "ok": True, **fields}


def response_error(req_id: Any, code: str, message: str) -> dict[str, Any]:
    return {
        "type": "response",
        "id": req_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }
