"""The only module that executes the `claude` CLI (documented subcommands only)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

_COPY_RE = re.compile(r"started a copy as ([0-9a-f]{6,})")
_BG_RE = re.compile(r"backgrounded \S+ ([0-9a-f]{6,})")


class ClaudeError(RuntimeError):
    """`claude` is missing, failed, or printed something unexpected."""


class ClaudeTimeout(ClaudeError):
    """`claude` did not finish in time; what it did before being killed is unknown."""


@dataclass(frozen=True)
class ResumeResult:
    short_id: Optional[str]
    forked_as: Optional[str]


# Where Claude Code's installers put `claude`. SSH runs bgpt-host in a non-login shell
# whose PATH usually leaves out ~/.local/bin.
_INSTALL_PATHS = ("~/.local/bin/claude", "~/.claude/local/claude")


def find_claude(
    which: Callable[[str], Optional[str]] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> str:
    found = which("claude")
    if found:
        return found
    for candidate in _INSTALL_PATHS:
        path = os.path.expanduser(candidate)
        if is_file(path):
            return path
    return "claude"  # not found: running it reports "claude not found"


class ClaudeCLI:
    def __init__(
        self,
        exe: Optional[Sequence[str]] = None,
        timeout: float = 60.0,
        run: Callable[..., Any] = subprocess.run,
    ):
        self._exe = list(exe) if exe is not None else [find_claude()]
        self._timeout = timeout
        self._run = run

    def _call(self, args: list[str], cwd: Optional[str] = None, combine: bool = False) -> str:
        if cwd is not None and not os.path.isdir(cwd):
            raise ClaudeError(f"working directory is missing: {cwd}")
        try:
            p = self._run(
                self._exe + args,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise ClaudeError("claude not found (is Claude Code installed and on PATH?)") from None
        except subprocess.TimeoutExpired:
            raise ClaudeTimeout(f"claude {args[0]} timed out") from None
        except OSError as e:
            raise ClaudeError(f"claude {args[0]} could not run: {e.strerror or e}") from None
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
        # Text starting with "-" would be parsed as a CLI option, so refuse it outright.
        if text.startswith("-"):
            raise ValueError("reply text must not start with '-'")
        out = self._call(["--resume", session_id, "--bg", text], cwd=cwd, combine=True)
        copy = _COPY_RE.search(out)
        bg = _BG_RE.search(out)
        short_id = bg.group(1) if bg else None
        forked_as = copy.group(1) if copy else None
        # Structural fallback: if the backgrounded id is not the session we asked for,
        # treat it as a fork even when the wording of the copy note has changed.
        if forked_as is None and short_id is not None:
            same = session_id.startswith(short_id) or short_id.startswith(session_id)
            if not same:
                forked_as = short_id
        return ResumeResult(short_id=short_id, forked_as=forked_as)

    def version(self) -> str:
        return self._call(["--version"]).strip()
