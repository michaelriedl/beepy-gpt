import json
import sys
import threading
import time
from pathlib import Path

from beepy_gpt.client.transport import Transport, ssh_argv

STUB = Path(__file__).parent / "stubs" / "fake_server.py"


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Recorder:
    def __init__(self):
        self.messages, self.statuses, self.lock = [], [], threading.Lock()

    def msg(self, m):
        with self.lock:
            self.messages.append(m)

    def status(self, s):
        with self.lock:
            self.statuses.append(s)

    def types(self):
        with self.lock:
            return [m["type"] for m in self.messages]


def make(tmp_path, mode):
    log = tmp_path / "server.log"
    rec = Recorder()
    t = Transport([sys.executable, str(STUB), str(log), mode], rec.msg, rec.status, backoff=(0.05,))
    return t, rec, log


def logged(log):
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def test_connects_and_receives_pushes(tmp_path):
    t, rec, _ = make(tmp_path, "ok")
    t.start()
    try:
        assert wait_for(lambda: "sessions" in rec.types())
        assert rec.messages[0] == {"type": "hello", "host_version": "9.9.9", "claude_version": "x", "claude_error": None}
        assert "online" in rec.statuses
    finally:
        t.stop()
    assert rec.statuses[-1] == "offline"


def test_request_response_correlation(tmp_path):
    t, rec, _ = make(tmp_path, "ok")
    t.start()
    got = []
    try:
        assert wait_for(lambda: "online" in rec.statuses)
        t.request("refresh", got.append)
        assert wait_for(lambda: got)
        assert got[0]["ok"] is True
    finally:
        t.stop()


def test_request_while_offline_fails_immediately(tmp_path):
    t, _, _ = make(tmp_path, "ok")
    got = []
    assert t.request("refresh", got.append) is None
    assert got[0]["error"]["code"] == "offline"


def test_inflight_request_fails_once_and_is_not_resent(tmp_path):
    t, rec, log = make(tmp_path, "drop")
    t.start()
    got = []
    try:
        assert wait_for(lambda: "online" in rec.statuses)
        t.request("reply", got.append, session_id="s", text="hi")
        assert wait_for(lambda: got)
        assert got == [got[0]] and got[0]["error"]["code"] == "lost"
        assert "may have been delivered" in got[0]["error"]["message"]
        assert wait_for(lambda: rec.statuses.count("online") >= 2)  # reconnected
        time.sleep(0.2)
        assert [m["type"] for m in logged(log)].count("reply") == 1
        assert len(got) == 1
    finally:
        t.stop()


def test_protocol_mismatch_is_fatal_and_does_not_reconnect(tmp_path):
    t, rec, log = make(tmp_path, "mismatch")
    t.start()
    try:
        assert wait_for(lambda: "fatal" in rec.types())
        assert wait_for(lambda: rec.statuses[-1:] == ["offline"])
        time.sleep(0.2)
        assert [m["type"] for m in logged(log)].count("hello") == 1
        assert rec.statuses[-1] == "offline"
        fatal = next(m for m in rec.messages if m["type"] == "fatal")
        assert "protocol" in fatal["message"]
    finally:
        t.stop()


def test_spawn_failure_reports_and_retries(tmp_path):
    rec = Recorder()
    t = Transport(["/nonexistent/ssh"], rec.msg, rec.status, backoff=(0.05,))
    t.start()
    try:
        assert wait_for(lambda: rec.types().count("host_error") >= 2)
    finally:
        t.stop()


def test_unicode_line_separators_do_not_split_messages(tmp_path):
    t, rec, _ = make(tmp_path, "unicode")
    t.start()
    try:
        assert wait_for(lambda: "note" in rec.types())
        note = next(m for m in rec.messages if m["type"] == "note")
        assert note["text"] == "a\u2028b\u2029c\u0085d"
    finally:
        t.stop()


def test_unknown_error_codes_pass_through(tmp_path):
    t, rec, _ = make(tmp_path, "internal")
    t.start()
    got = []
    try:
        assert wait_for(lambda: "online" in rec.statuses)
        t.request("refresh", got.append)
        assert wait_for(lambda: got)
        assert got[0]["error"] == {"code": "internal", "message": "boom"}
    finally:
        t.stop()


def test_malformed_response_id_does_not_kill_reader(tmp_path):
    t, rec, _ = make(tmp_path, "badid")
    t.start()
    got = []
    try:
        assert wait_for(lambda: "online" in rec.statuses)
        t.request("refresh", got.append)
        assert wait_for(lambda: got)
        assert got[0]["ok"] is True
        t.request("refresh", got.append)
        assert wait_for(lambda: len(got) == 2)
    finally:
        t.stop()


def test_raising_callback_does_not_stop_later_responses(tmp_path):
    t, rec, _ = make(tmp_path, "ok")
    t.start()
    got = []

    def boom(_r):
        raise RuntimeError("callback bug")

    try:
        assert wait_for(lambda: "online" in rec.statuses)
        t.request("refresh", boom)
        t.request("refresh", got.append)
        assert wait_for(lambda: got)
        assert got[0]["ok"] is True
        assert rec.statuses.count("online") == 1
    finally:
        t.stop()


def test_malformed_hello_error_reconnects(tmp_path):
    t, rec, log = make(tmp_path, "badhello")
    t.start()
    try:
        assert wait_for(lambda: rec.types().count("host_error") >= 2)
        assert "online" not in rec.statuses
    finally:
        t.stop()


def test_no_online_after_stop(tmp_path):
    for _ in range(5):
        t, rec, _ = make(tmp_path, "ok")
        t.start()
        t.stop()
        assert rec.statuses[-1] == "offline"
        assert "online" not in rec.statuses[rec.statuses.index("offline"):]


def test_ssh_argv():
    assert ssh_argv("user@workstation", ["-p", "2222"], "bgpt-host") == [
        "ssh", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
        "-p", "2222", "user@workstation", "bgpt-host", "serve",
    ]
