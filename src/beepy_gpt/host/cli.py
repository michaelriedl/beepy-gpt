"""`bgpt-host` command line entry point."""

from __future__ import annotations

import argparse
import atexit
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from beepy_gpt import __version__
from beepy_gpt.config import load_host_config


def _yes(diff: str) -> bool:
    return True


def _confirm(diff: str) -> bool:
    try:
        return input("Apply these changes? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="bgpt-host", description="Workstation helper for beepy-gpt")
    p.add_argument("--version", action="version", version=f"bgpt-host {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve", help="speak the beepy-gpt protocol on stdio (run by the client over ssh)")
    sp.add_argument("--fake", action="store_true", help="use scripted fake sessions (development)")
    sp.add_argument("--exit-after", type=float, default=None, metavar="SECONDS",
                    help="exit after SECONDS (development: simulates a dropped connection)")
    sub.add_parser("hook", help="PermissionRequest hook entry (called by Claude Code)")
    for name in ("install-hook", "uninstall-hook"):
        x = sub.add_parser(name)
        x.add_argument("--yes", action="store_true", help="do not ask for confirmation")
        x.add_argument("--settings", type=Path, default=None, help="Claude Code settings.json path")
    sub.add_parser("doctor", help="check the workstation setup")
    args = p.parse_args(argv)

    if args.cmd == "hook":
        from beepy_gpt.host import hook

        return hook.main()

    cfg = load_host_config()

    if args.cmd == "serve":
        from beepy_gpt.host.approvals import Spool
        from beepy_gpt.host.serve import Server, serve_stdio, stdout_writer

        if args.fake:
            from beepy_gpt.host.fake import FakeClaude

            workdir = Path(tempfile.mkdtemp(prefix="bgpt-fake-"))
            atexit.register(shutil.rmtree, workdir, True)
            spool = Spool(workdir / "approvals")
            backend = FakeClaude(workdir, spool)
            transcript_for = backend.transcript_for
        else:
            from beepy_gpt.host.claude_cli import ClaudeCLI
            from beepy_gpt.host.transcripts import claude_home, transcript_path

            spool = Spool(cfg.state_dir / "approvals", audit_log=cfg.state_dir / "audit.log")
            spool.cleanup()
            backend = ClaudeCLI()
            home = claude_home()

            def transcript_for(s):
                return transcript_path(home, s.cwd, s.session_id)

        server = Server(backend, spool, stdout_writer(), transcript_for, poll_seconds=cfg.agents_poll_seconds)
        serve_stdio(server, sys.stdin.fileno(), exit_after=args.exit_after)
        return 0

    if args.cmd in ("install-hook", "uninstall-hook"):
        from beepy_gpt.host.install import (
            default_settings_path, hook_command, plan_install, plan_uninstall, run_change,
        )

        path = args.settings or default_settings_path()
        if args.cmd == "install-hook":
            cmd, timeout = hook_command(), cfg.hook_timeout_seconds + 30

            def change(s):
                return plan_install(s, cmd, timeout)
        else:
            change = plan_uninstall
        return run_change(path, change, _yes if args.yes else _confirm, print)

    if args.cmd == "doctor":
        from beepy_gpt.host.claude_cli import ClaudeCLI
        from beepy_gpt.host.doctor import run_doctor
        from beepy_gpt.host.install import default_settings_path

        return run_doctor(ClaudeCLI(), cfg, default_settings_path(), print)
    return 2


if __name__ == "__main__":
    sys.exit(main())
