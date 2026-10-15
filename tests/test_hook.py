import json

import pytest

from beepy_gpt.host.approvals import Spool
from beepy_gpt.host.hook import decision_output, is_interactive, run_hook
from helpers import agent

SID = "aaaa1111-0000-4000-8000-000000000000"
STDIN = json.dumps({
    "session_id": SID,
    "cwd": "/home/dev/proj",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "touch b1.txt", "description": "Create b1"},
})
BG_ENV = {"CLAUDE_JOB_DIR": "/tmp/job", "CLAUDE_CODE_SESSION_ATTENDED": "0"}


@pytest.fixture
def spool(tmp_path, clock):
    return Spool(tmp_path / "approvals", audit_log=tmp_path / "audit.log", clock=clock)


def bg_agents():
    return [agent()]


def test_is_interactive_signals():
    assert is_interactive({}, SID, bg_agents) is True
    assert is_interactive(BG_ENV, SID, lambda: [agent(kind="interactive")]) is True
    assert is_interactive(BG_ENV, SID, bg_agents) is False
    assert is_interactive(BG_ENV, SID, lambda: []) is False

    def boom():
        raise RuntimeError("x")

    assert is_interactive(BG_ENV, SID, boom) is True


def test_interactive_passes_through_without_spooling(spool, clock):
    assert run_hook(STDIN, {}, spool, 60, bg_agents, sleep=clock.sleep) == ""
    assert not spool.root.exists() or not list(spool.root.iterdir())


def test_background_allow(spool, clock):
    def sleep(s):
        clock.sleep(s)
        [req] = spool.pending()
        spool.decide(req.request_id, "allow")

    out = run_hook(STDIN, BG_ENV, spool, 60, bg_agents, poll=1, sleep=sleep)
    assert json.loads(out) == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow", "message": ""},
        }
    }


def test_background_deny_with_message(spool, clock):
    def sleep(s):
        clock.sleep(s)
        spool.decide(spool.pending()[0].request_id, "deny", "not now")

    out = run_hook(STDIN, BG_ENV, spool, 60, bg_agents, poll=1, sleep=sleep)
    assert json.loads(out)["hookSpecificOutput"]["decision"] == {"behavior": "deny", "message": "not now"}


def test_timeout_gives_no_decision_and_audits(spool, clock, tmp_path):
    assert run_hook(STDIN, BG_ENV, spool, 5, bg_agents, poll=1, sleep=clock.sleep) == ""
    events = [json.loads(x)["event"] for x in (tmp_path / "audit.log").read_text().splitlines()]
    assert events == ["request", "timeout"]


@pytest.mark.parametrize("stdin", ["", "{not json", json.dumps({"hook_event_name": "Stop"})])
def test_bad_or_other_input_gives_nothing(spool, clock, stdin):
    assert run_hook(stdin, BG_ENV, spool, 5, bg_agents, sleep=clock.sleep) == ""


def test_unwritable_spool_gives_nothing(tmp_path, clock):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    spool = Spool(blocker / "approvals", clock=clock)
    assert run_hook(STDIN, BG_ENV, spool, 5, bg_agents, sleep=clock.sleep) == ""


def test_decision_output_shape():
    out = decision_output("deny", "m")
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {
        "hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": "m"}}
    }


def test_decision_accepted_just_before_expiry_is_picked_up(spool, clock):
    calls = []

    def sleep(s):
        calls.append(s)
        clock.t = 1000.0 + 59.9  # just before expires_at (1060)
        spool.decide(spool.pending()[0].request_id, "allow")
        clock.t = 1000.0 + 60.5  # now past `timeout`, inside the grace window

    out = run_hook(STDIN, BG_ENV, spool, 60, bg_agents, poll=1, sleep=sleep)
    assert json.loads(out)["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_wait_uses_timeout_plus_grace(spool, clock, monkeypatch):
    seen = []
    monkeypatch.setattr(spool, "wait_decision", lambda rid, t, **kw: seen.append(t))
    assert run_hook(STDIN, BG_ENV, spool, 60, bg_agents, sleep=clock.sleep) == ""
    assert seen == [62.0]
