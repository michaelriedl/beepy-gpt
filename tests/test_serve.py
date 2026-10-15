import json
import os

import pytest

from beepy_gpt.host.approvals import Spool
from beepy_gpt.host.claude_cli import ClaudeError, ResumeResult
from beepy_gpt.host.serve import Server, serve_stdio
from beepy_gpt.protocol import PROTOCOL_VERSION, encode
from helpers import agent

SID = "aaaa1111-0000-4000-8000-000000000000"


class Backend:
    def __init__(self, records):
        self.records = records
        self.calls = []
        self.fail = None

    def agents(self, include_all=False):
        if self.fail:
            raise ClaudeError(self.fail)
        return self.records

    def stop(self, short_id):
        self.calls.append(("stop", short_id))

    def resume_bg(self, session_id, text, cwd):
        self.calls.append(("resume", session_id, text))
        return ResumeResult(short_id=session_id[:8], forked_as=None)

    def version(self):
        return "2.1.300 (Claude Code)"


@pytest.fixture
def env(tmp_path, clock):
    out = []
    cwd = tmp_path / "proj"
    cwd.mkdir()
    backend = Backend([agent(state="done", status="idle", waitingFor=None, cwd=str(cwd))])
    spool = Spool(tmp_path / "approvals", clock=clock)
    transcript = tmp_path / "t.jsonl"
    server = Server(backend, spool, out.append, lambda s: transcript, poll_seconds=3, clock=clock)
    return server, backend, spool, out, transcript


def hello(server):
    server.handle({"type": "hello", "id": 0, "v": PROTOCOL_VERSION})


def types(out):
    return [m["type"] for m in out]


def test_protocol_mismatch(env):
    server, _, _, out, _ = env
    server.handle({"type": "hello", "id": 0, "v": 999})
    assert out == [{
        "type": "response", "id": 0, "ok": False,
        "error": {"code": "protocol_mismatch", "message": f"client protocol 999, host protocol {PROTOCOL_VERSION}"},
    }]


def test_requests_before_hello_rejected(env):
    server, _, _, out, _ = env
    server.handle({"type": "refresh", "id": 1})
    assert out[0]["error"]["code"] == "no_hello"


def test_hello_pushes_snapshots(env):
    server, _, _, out, _ = env
    hello(server)
    assert types(out) == ["response", "sessions", "approvals"]
    assert out[0]["ok"] and out[0]["claude_version"] == "2.1.300 (Claude Code)"
    assert out[1]["sessions"][0]["session_id"] == SID


def test_tick_pushes_only_changes(env, clock):
    server, backend, _, out, _ = env
    hello(server)
    out.clear()
    clock.sleep(5)
    server.tick()
    assert out == []
    backend.records = [agent()]
    clock.sleep(5)
    server.tick()
    assert types(out) == ["sessions"]


def test_tick_respects_poll_interval(env, clock):
    server, backend, _, out, _ = env
    hello(server)
    out.clear()
    backend.records = [agent()]
    clock.sleep(1)
    server.tick()
    assert out == []


def test_approvals_pushed_with_session_context(env):
    server, _, spool, out, _ = env
    hello(server)
    out.clear()
    spool.create({"session_id": SID, "cwd": "/home/dev/proj", "tool_name": "Bash",
                  "tool_input": {"command": "ls"}}, timeout=60)
    server.tick()
    [msg] = out
    assert msg["type"] == "approvals"
    assert msg["approvals"][0]["project"] == "proj" and msg["approvals"][0]["session_name"] == "demo"


def test_decide_ok_and_twice(env):
    server, _, spool, out, _ = env
    hello(server)
    req = spool.create({"session_id": SID, "tool_name": "Bash", "tool_input": {}}, timeout=60)
    out.clear()
    server.handle({"type": "decide", "id": 5, "request_id": req.request_id, "behavior": "allow"})
    server.handle({"type": "decide", "id": 6, "request_id": req.request_id, "behavior": "allow"})
    responses = [m for m in out if m["type"] == "response"]
    assert responses[0]["ok"] is True
    assert responses[1]["error"]["code"] == "already_decided"


def test_reply_ok_and_guard_error(env):
    server, backend, _, out, _ = env
    hello(server)
    out.clear()
    server.handle({"type": "reply", "id": 7, "session_id": SID, "text": "go"})
    assert out[0] == {"type": "response", "id": 7, "ok": True, "forked_as": None}
    assert ("resume", SID, "go") in backend.calls
    backend.records = [agent(kind="interactive")]
    out.clear()
    server.handle({"type": "reply", "id": 8, "session_id": SID, "text": "go"})
    assert out[0]["error"]["code"] == "interactive"


def test_feed_and_append(env):
    server, _, _, out, transcript = env
    transcript.write_text(json.dumps({"type": "user", "message": {"content": "first"}}) + "\n")
    hello(server)
    out.clear()
    server.handle({"type": "feed", "id": 9, "session_id": SID})
    assert out[0]["events"] == [{"kind": "you", "text": "first", "ok": None}]
    out.clear()
    with transcript.open("a") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "second"}}) + "\n")
    server.tick()
    assert out == [{"type": "feed_append", "session_id": SID,
                    "events": [{"kind": "you", "text": "second", "ok": None}]}]
    server.handle({"type": "close_feed", "id": 10})
    with transcript.open("a") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "third"}}) + "\n")
    out.clear()
    server.tick()
    assert out == []


def test_feed_unknown_session(env):
    server, _, _, out, _ = env
    hello(server)
    out.clear()
    server.handle({"type": "feed", "id": 11, "session_id": "nope"})
    assert out[0]["error"]["code"] == "unknown_session"


def test_host_error_pushed_once(env, clock):
    server, backend, _, out, _ = env
    hello(server)
    out.clear()
    backend.fail = "claude agents failed: Not logged in"
    for _ in range(3):
        clock.sleep(5)
        server.tick()
    assert types(out) == ["host_error"]


def test_unknown_type(env):
    server, _, _, out, _ = env
    hello(server)
    out.clear()
    server.handle({"type": "bogus", "id": 12})
    assert out[0]["error"]["code"] == "unknown_type"


def test_serve_stdio_handles_lines_and_eof(env):
    server, _, _, out, _ = env
    r, w = os.pipe()
    os.write(w, encode({"type": "hello", "id": 0}).encode() + b"garbage\n")
    os.close(w)
    serve_stdio(server, r, tick_seconds=0.01)
    os.close(r)
    assert out[0]["ok"] is True
    assert any(m.get("error", {}).get("code") == "bad_message" for m in out)


def test_decide_oserror_becomes_error_and_server_continues(env, monkeypatch):
    server, _, spool, out, _ = env
    hello(server)
    out.clear()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(spool, "decide", boom)
    server.handle({"type": "decide", "id": 20, "request_id": "x", "behavior": "allow"})
    assert out[0]["ok"] is False and out[0]["error"]["code"] == "internal"
    assert "disk full" in out[0]["error"]["message"]
    out.clear()
    server.handle({"type": "refresh", "id": 21})
    assert out[0] == {"type": "response", "id": 21, "ok": True}


def test_claude_error_in_handler(env):
    server, backend, _, out, _ = env
    hello(server)
    out.clear()
    backend.fail = "claude agents failed: nope"
    server.handle({"type": "reply", "id": 22, "session_id": SID, "text": "go"})
    assert out[0]["error"]["code"] == "claude_error"


def test_serve_stdio_does_not_split_on_unicode_separators(env):
    server, _, _, out, _ = env
    r, w = os.pipe()
    data = encode({"type": "hello", "id": 0}).encode()
    data += encode({"type": "reply", "id": 1, "session_id": SID, "text": "a\u2028b\u2029c\x85d"}).encode()
    os.write(w, data)
    os.close(w)
    serve_stdio(server, r, tick_seconds=0.01)
    os.close(r)
    assert not any(m.get("error", {}).get("code") == "bad_message" for m in out)
    assert ("resume", SID, "a\u2028b\u2029c\x85d") in server.backend.calls


def test_persistent_poll_error_reported_once_until_recovery(env, clock):
    server, backend, _, out, _ = env
    hello(server)
    out.clear()
    calls = {"n": 0}
    good = backend.records

    def failing(include_all=False):
        calls["n"] += 1
        raise RuntimeError("odd")

    backend.agents = failing
    for _ in range(9):
        clock.sleep(1)
        server.tick()
    assert calls["n"] >= 2
    assert [m["type"] for m in out] == ["host_error"]
    del backend.agents
    backend.records = good
    clock.sleep(5)
    server.tick()
    backend.agents = failing
    clock.sleep(5)
    server.tick()
    assert [m["type"] for m in out].count("host_error") == 2


def test_feed_cache_miss_repolls(env):
    server, backend, _, out, transcript = env
    transcript.write_text("")
    backend.records = []
    hello(server)
    backend.records = [agent(state="done", status="idle", waitingFor=None)]
    out.clear()
    server.handle({"type": "feed", "id": 30, "session_id": SID})
    assert out[0]["ok"] is True
    out.clear()
    server.handle({"type": "feed", "id": 31, "session_id": "nope"})
    assert out[0]["error"]["code"] == "unknown_session"


def test_hello_failure_becomes_error(env):
    server, backend, _, out, _ = env

    def boom():
        raise RuntimeError("x")

    backend.version = boom
    server.handle({"type": "hello", "id": 0, "v": PROTOCOL_VERSION})
    assert out[0]["error"]["code"] == "internal"
