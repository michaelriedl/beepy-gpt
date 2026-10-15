"""The only module that executes the `claude` CLI (documented subcommands only)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

_COPY_RE = re.compile(r"started a copy as ([0-9a-f]{6,})")
_BG_RE = re.compile(r"backgrounded \S+ ([0-9a-f]{6,})")


class ClaudeError(RuntimeError):
    """`claude` is missing, failed, or printed something unexpected."""


@dataclass(frozen=True)
class ResumeResult:
    short_id: Optional[str]
    forked_as: Optional[str]


class ClaudeCLI:
    def __init__(
        self,
        exe: Sequence[str] = ("claude",),
        timeout: float = 60.0,
        run: Callable[..., Any] = subprocess.run,
    ):
        self._exe = list(exe)
        self._timeout = timeout
        self._run = run

    def _call(self, args: list[str], cwd: Optional[str] = None, combine: bool = False) -> str:
        try:
            p = self._run(
                self._exe + args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise ClaudeError("claude not found (is Claude Code installed and on PATH?)") from None
        except subprocess.TimeoutExpired:
            raise ClaudeError(f"claude {args[0]} timed out") from None
        if p.returncode != 0:
            lines = (p.stderr or p.stdout or "").strip().splitlines()
            detail = lines[-1] if lines else f"exit {p.returncode}"
            raise ClaudeError(f"claude {args[0]} failed: {detail}")
        return (p.stdout or "") + ("\n" + (p.stderr or "") if combine else "")

    def agents(self, include_all: bool = False) -> list[dict]:
        out = self._call(["agents", "--json"] + (["--all"] if include_all else []))
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise ClaudeError(f"claude agents --json: bad json: {e}") from None
        if not isinstance(data, list):
            raise ClaudeError("claude agents --json: expected a list")
        return [a for a in data if isinstance(a, dict)]

    def stop(self, short_id: str) -> None:
        self._call(["stop", short_id])

    def resume_bg(self, session_id: str, text: str, cwd: str) -> ResumeResult:
        # No other flags: any flag on resume makes Claude Code start a copy (spec §2 #4).
        out = self._call(["--resume", session_id, "--bg", text], cwd=cwd, combine=True)
        copy = _COPY_RE.search(out)
        bg = _BG_RE.search(out)
        return ResumeResult(
            short_id=bg.group(1) if bg else None,
            forked_as=copy.group(1) if copy else None,
        )

    def version(self) -> str:
        return self._call(["--version"]).strip()
