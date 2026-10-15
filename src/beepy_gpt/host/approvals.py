"""Spool directory holding pending permission requests and their decisions."""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

BEHAVIORS = ("allow", "deny")


class SpoolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    session_id: str
    cwd: str
    tool_name: str
    tool_input: dict
    description: str
    created_at: float
    expires_at: float
    pid: Optional[int] = None  # the waiting hook process; None for older requests

    def to_wire(self) -> dict:
        d = asdict(self)
        d.pop("pid")  # host-side bookkeeping only
        return d

    @property
    def hook_gone(self) -> bool:
        """The hook that would apply a decision has exited (e.g. its session stopped)."""
        if not isinstance(self.pid, int) or self.pid <= 0:
            return False
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return True
        except OSError:  # PermissionError and the like: it exists
            return False
        return False


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Spool:
    def __init__(
        self,
        root: Path,
        audit_log: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.root = Path(root)
        self.audit_log = audit_log
        self._clock = clock

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _req(self, rid: str) -> Path:
        return self.root / f"{rid}.json"

    def _dec(self, rid: str) -> Path:
        return self.root / f"{rid}.decision"

    def create(self, payload: dict, timeout: float, pid: Optional[int] = None) -> ApprovalRequest:
        self._ensure()
        now = self._clock()
        tool_input = payload.get("tool_input")
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        req = ApprovalRequest(
            request_id=f"{int(now * 1000)}-{secrets.token_hex(4)}",
            session_id=str(payload.get("session_id", "")),
            cwd=str(payload.get("cwd", "")),
            tool_name=str(payload.get("tool_name", "")),
            tool_input=tool_input,
            description=str(tool_input.get("description", "")),
            created_at=now,
            expires_at=now + timeout,
            pid=pid,
        )
        _atomic_write(self._req(req.request_id), json.dumps(asdict(req)))
        self.audit("request", request_id=req.request_id, session_id=req.session_id, tool=req.tool_name)
        return req

    def get(self, rid: str) -> Optional[ApprovalRequest]:
        if not rid or "/" in rid:
            return None
        try:
            return ApprovalRequest(**json.loads(self._req(rid).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def pending(self) -> list[ApprovalRequest]:
        if not self.root.is_dir():
            return []
        now = self._clock()
        out = []
        for p in sorted(self.root.glob("*.json")):
            req = self.get(p.stem)
            if req and req.expires_at > now and not self._dec(req.request_id).exists() and not req.hook_gone:
                out.append(req)
        return sorted(out, key=lambda r: r.created_at)

    def decide(self, rid: str, behavior: str, message: str = "") -> None:
        if behavior not in BEHAVIORS:
            raise SpoolError("bad_request", f"behavior must be allow or deny, not {behavior!r}")
        req = self.get(rid)
        if req is None:
            raise SpoolError("unknown_request", "no such request")
        if self._clock() >= req.expires_at or req.hook_gone:
            raise SpoolError("expired", "request expired")
        tmp = self.root / f".{rid}.{secrets.token_hex(4)}.tmp"
        tmp.write_text(
            json.dumps({"behavior": behavior, "message": message, "decided_at": self._clock()}),
            encoding="utf-8",
        )
        try:
            os.link(tmp, self._dec(rid))  # atomic; fails if a decision already exists
        except FileExistsError:
            raise SpoolError("already_decided", "request already decided") from None
        finally:
            tmp.unlink()
        self.audit("decision", request_id=rid, behavior=behavior)

    def read_decision(self, rid: str) -> Optional[dict]:
        try:
            d = json.loads(self._dec(rid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(d, dict) or d.get("behavior") not in BEHAVIORS:
            return None
        d.setdefault("message", "")
        return d

    def wait_decision(
        self,
        rid: str,
        timeout: float,
        poll: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Optional[dict]:
        deadline = self._clock() + timeout
        while True:
            d = self.read_decision(rid)
            if d is not None:
                return d
            if self._clock() >= deadline:
                return None
            sleep(poll)

    def audit(self, event: str, **fields: object) -> None:
        if self.audit_log is None:
            return
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": self._clock(), "event": event, **fields}) + "\n")

    def cleanup(self, max_age: float = 86400) -> None:
        if not self.root.is_dir():
            return
        cutoff = self._clock() - max_age
        for p in self.root.glob("*.json"):
            req = self.get(p.stem)
            if req is not None and req.created_at < cutoff:
                self._dec(p.stem).unlink(missing_ok=True)
                p.unlink(missing_ok=True)
        for p in self.root.glob("*.decision"):
            if not self._req(p.stem).exists():
                p.unlink(missing_ok=True)
