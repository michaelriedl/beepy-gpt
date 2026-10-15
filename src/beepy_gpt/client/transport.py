"""One long-lived `ssh <target> bgpt-host serve` process speaking JSON lines."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from beepy_gpt import __version__
from beepy_gpt.protocol import PROTOCOL_VERSION, ProtocolError, decode, encode, response_error

BACKOFF = (1, 2, 4, 8, 16, 30)
OFFLINE_MESSAGE = "not connected; nothing was sent"


def ssh_argv(target: str, options: list[str], host_command: str) -> list[str]:
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
        *options, target, host_command, "serve",
    ]


class Transport:
    def __init__(
        self,
        argv: list[str],
        on_message: Callable[[dict], None],
        on_status: Callable[[str], None],
        client_version: str = __version__,
        backoff: tuple = BACKOFF,
        popen: Callable[..., Any] = subprocess.Popen,
        stderr_path: Optional[Path] = None,
    ):
        self._argv = argv
        self._on_message = on_message
        self._on_status = on_status
        self._client_version = client_version
        self._backoff = backoff
        self._popen = popen
        self._stderr_path = stderr_path
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._proc: Any = None
        self._online = False
        self._pending: dict = {}
        self._next_id = 1
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="bgpt-transport", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        with self._lock:
            proc = self._proc
        if proc is not None:
            self._kill(proc)
        if self._thread is not None:
            self._thread.join(timeout=3)

    def request(self, type_: str, callback: Optional[Callable[[dict], None]] = None, **fields: Any) -> Optional[int]:
        cb = callback or (lambda r: None)
        with self._lock:
            proc = self._proc
            if self._online and proc is not None and proc.stdin is not None:
                rid = self._next_id
                self._next_id += 1
                self._pending[rid] = cb
                try:
                    proc.stdin.write(encode({"type": type_, "id": rid, **fields}))
                    proc.stdin.flush()
                    return rid
                except (OSError, ValueError):
                    self._pending.pop(rid, None)
        cb(response_error(None, "offline", OFFLINE_MESSAGE))
        return None

    # --- internals ------------------------------------------------------
    def _spawn(self) -> Any:
        err = open(self._stderr_path, "a") if self._stderr_path else subprocess.DEVNULL
        try:
            proc = self._popen(
                self._argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as e:
            self._on_message({"type": "host_error", "message": f"cannot start {self._argv[0]}: {e.strerror or e}"})
            return None
        finally:
            if err is not subprocess.DEVNULL:
                err.close()
        with self._lock:
            self._proc = proc
        return proc

    def _kill(self, proc: Any) -> None:
        for step in (lambda: proc.stdin and proc.stdin.close(), proc.terminate):
            try:
                step()
            except (OSError, ValueError):
                pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _handshake(self, proc: Any) -> str:
        try:
            proc.stdin.write(encode({"type": "hello", "id": 0, "client_version": self._client_version}))
            proc.stdin.flush()
        except (OSError, ValueError):
            return "retry"
        for line in proc.stdout:
            try:
                msg = decode(line)
            except ProtocolError:
                continue
            if msg.get("type") != "response" or msg.get("id") != 0:
                self._on_message(msg)
                continue
            if msg.get("ok"):
                with self._lock:
                    self._online = True
                self._on_message({
                    "type": "hello", "host_version": msg.get("host_version", ""),
                    "claude_version": msg.get("claude_version", ""), "claude_error": msg.get("claude_error"),
                })
                return "ok"
            err = msg.get("error") or {}
            if err.get("code") == "protocol_mismatch":
                self._on_message({
                    "type": "fatal",
                    "message": f"protocol mismatch ({err.get('message')}; this client speaks "
                    f"{PROTOCOL_VERSION}). Upgrade beepy-gpt on both machines.",
                })
                return "fatal"
            self._on_message({"type": "host_error", "message": str(err.get("message", "hello failed"))})
            return "retry"
        return "retry"

    def _read_loop(self, proc: Any) -> None:
        for line in proc.stdout:
            try:
                msg = decode(line)
            except ProtocolError:
                continue
            if msg.get("type") == "response":
                with self._lock:
                    cb = self._pending.pop(msg.get("id"), None)
                if cb is not None:
                    cb(msg)
                continue
            self._on_message(msg)

    def _fail_pending(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
        for rid, cb in pending.items():
            cb(response_error(rid, "offline", OFFLINE_MESSAGE))

    def _run(self) -> None:
        attempt = 0
        while not self._stopped.is_set():
            self._on_status("connecting" if attempt == 0 else "reconnecting")
            proc = self._spawn()
            if proc is not None:
                result = self._handshake(proc)
                if result == "ok":
                    attempt = 0
                    self._on_status("online")
                    self._read_loop(proc)
                with self._lock:
                    self._online = False
                    self._proc = None
                self._fail_pending()
                self._kill(proc)
                if result == "fatal":
                    break
            if self._stopped.is_set():
                break
            self._on_status("reconnecting")
            self._stopped.wait(self._backoff[min(attempt, len(self._backoff) - 1)])
            attempt += 1
        self._on_status("offline")
