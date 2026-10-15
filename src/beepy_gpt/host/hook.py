"""`bgpt-host hook`: Claude Code PermissionRequest hook. Never allows by default."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Callable, Mapping

from beepy_gpt.config import load_host_config
from beepy_gpt.host.approvals import Spool

# The request expires at `timeout`, but Spool.decide() checks expiry before writing,
# so a decision accepted just before expires_at could land after our last read.
DECISION_GRACE_SECONDS = 2.0


def is_interactive(
    env: Mapping[str, str], session_id: str, agents: Callable[[], list]
) -> bool:
    # CLAUDE_JOB_DIR is undocumented, so cross-check with the documented `kind`.
    # Interactive (pass through) if the env says so, if `agents --json` lists the
    # session with a non-background kind, or if `agents --json` fails. A session
    # that `agents --json` does not list is judged by the env signal alone.
    if not env.get("CLAUDE_JOB_DIR"):
        return True
    try:
        for a in agents():
            if isinstance(a, dict) and a.get("sessionId") == session_id:
                return a.get("kind") != "background"
    except Exception:
        return True
    return False


def decision_output(behavior: str, message: str) -> str:
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": behavior, "message": message},
        }
    }) + "\n"


def run_hook(
    stdin_text: str,
    env: Mapping[str, str],
    spool: Spool,
    timeout: float,
    agents: Callable[[], list],
    poll: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    try:
        payload = json.loads(stdin_text)
        if not isinstance(payload, dict) or payload.get("hook_event_name") != "PermissionRequest":
            return ""
        if is_interactive(env, str(payload.get("session_id", "")), agents):
            return ""
        req = spool.create(payload, timeout)
        decision = spool.wait_decision(
            req.request_id, timeout + DECISION_GRACE_SECONDS, poll=poll, sleep=sleep)
        if decision is None:
            spool.audit("timeout", request_id=req.request_id)
            return ""
        return decision_output(decision["behavior"], str(decision.get("message", "")))
    except Exception:
        return ""


def main() -> int:
    out = ""
    try:
        from beepy_gpt.host.claude_cli import ClaudeCLI

        cfg = load_host_config()
        spool = Spool(cfg.state_dir / "approvals", audit_log=cfg.state_dir / "audit.log")
        out = run_hook(sys.stdin.read(), os.environ, spool, cfg.hook_timeout_seconds, ClaudeCLI().agents)
    except Exception:
        out = ""
    if out:
        sys.stdout.write(out)
        sys.stdout.flush()
    return 0
