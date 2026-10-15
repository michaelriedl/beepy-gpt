import pytest

from beepy_gpt.host.actions import ActionError, prepare_text, reply
from helpers import agent

SID = "aaaa1111-0000-4000-8000-000000000000"
FORK = "note: ... so this started a copy as 9ad97bf9.\nbackgrounded · 9ad97bf9\n"


def argvs(stub):
    return [c["argv"] for c in stub.calls()]


def test_running_session_is_stopped_then_resumed_without_flags(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="blocked", status="idle", waitingFor=None, cwd=str(tmp_path))])
    assert reply(stub_claude.cli(), "aaaa1111", "  hello  ") == {"forked_as": None}
    assert argvs(stub_claude) == [
        ["agents", "--json", "--all"],
        ["agents", "--json", "--all"],
        ["stop", "aaaa1111"],
        ["--resume", SID, "--bg", "hello"],
    ]
    assert stub_claude.calls()[-1]["cwd"] == str(tmp_path)


def test_stopped_session_is_resumed_directly(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="stopped", status=None, waitingFor=None, pid=None, cwd=str(tmp_path))])
    reply(stub_claude.cli(), SID, "go")
    assert argvs(stub_claude) == [["agents", "--json", "--all"], ["--resume", SID, "--bg", "go"]]


@pytest.mark.parametrize(
    "rec,code",
    [
        (agent(kind="interactive"), "interactive"),
        (agent(state="working", status=None, waitingFor=None), "working"),
        (agent(state="working", status="waiting", waitingFor="permission prompt"), "working"),
    ],
)
def test_guarded_sessions_are_refused_without_side_effects(stub_claude, rec, code):
    stub_claude.set_agents([rec])
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), "aaaa1111", "hi")
    assert e.value.code == code
    assert argvs(stub_claude) == [["agents", "--json", "--all"]]


def test_reply_unknown_session(stub_claude):
    stub_claude.set_agents([])
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), "aaaa1111", "hi")
    assert e.value.code == "unknown_session"


def test_reply_rechecks_state_before_stopping(stub_claude):
    stub_claude.set_agents(
        [agent(state="blocked", status="idle", waitingFor=None)],
        [agent(state="working", status=None, waitingFor=None)],
    )
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), "aaaa1111", "hi")
    assert e.value.code == "working"
    assert ["stop", "aaaa1111"] not in argvs(stub_claude)


def test_fork_is_reported(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="stopped", pid=None, waitingFor=None, status=None, cwd=str(tmp_path))])
    stub_claude.set_resume_output(FORK)
    assert reply(stub_claude.cli(), SID, "hi") == {"forked_as": "9ad97bf9"}


def test_claude_failure_becomes_action_error(stub_claude):
    stub_claude.fail(stderr="Not logged in")
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), SID, "hi")
    assert e.value.code == "claude_error" and "Not logged in" in e.value.message


def test_dash_led_reply_is_space_prefixed_before_resume(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="stopped", status=None, waitingFor=None, pid=None, cwd=str(tmp_path))])
    reply(stub_claude.cli(), SID, "--help me")
    assert argvs(stub_claude)[-1] == ["--resume", SID, "--bg", " --help me"]


def test_missing_cwd_becomes_claude_error(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="stopped", status=None, waitingFor=None, pid=None, cwd=str(tmp_path / "gone"))])
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), SID, "hi")
    assert e.value.code == "claude_error"
    assert argvs(stub_claude) == [["agents", "--json", "--all"]]


def test_prepare_text():
    assert prepare_text("-x") == " -x"
    with pytest.raises(ActionError):
        prepare_text("   ")


def test_running_session_with_missing_cwd_is_not_stopped(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="blocked", status="idle", waitingFor=None, cwd=str(tmp_path / "gone"))])
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), "aaaa1111", "hi")
    assert e.value.code == "claude_error" and "working directory is missing" in e.value.message
    assert ["stop", "aaaa1111"] not in argvs(stub_claude)


def test_session_vanishing_on_recheck_is_not_stopped(stub_claude):
    stub_claude.set_agents([agent(state="blocked", status="idle", waitingFor=None)], [])
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), "aaaa1111", "hi")
    assert e.value.code == "unknown_session"
    assert ["stop", "aaaa1111"] not in argvs(stub_claude)


def test_resume_failure_after_stop_says_session_was_stopped(stub_claude, tmp_path):
    from beepy_gpt.host.claude_cli import ClaudeError

    stub_claude.set_agents([agent(state="blocked", status="idle", waitingFor=None, cwd=str(tmp_path))])
    real = stub_claude.cli()

    class Backend:
        agents = staticmethod(real.agents)
        stop = staticmethod(real.stop)

        @staticmethod
        def resume_bg(*a, **k):
            raise ClaudeError("claude --resume failed: boom")

    with pytest.raises(ActionError) as e:
        reply(Backend, "aaaa1111", "hi")
    assert e.value.code == "claude_error"
    assert e.value.message.startswith("session was stopped but the reply was not sent: ")
    assert "boom" in e.value.message
    assert ["stop", "aaaa1111"] in argvs(stub_claude)


def test_finished_session_from_all_is_replyable(stub_claude, tmp_path):
    stub_claude.set_agents([agent(state="stopped", status=None, waitingFor=None, pid=None, cwd=str(tmp_path))])
    assert reply(stub_claude.cli(), "aaaa1111", "wake up") == {"forked_as": None}
    assert argvs(stub_claude) == [["agents", "--json", "--all"], ["--resume", SID, "--bg", "wake up"]]


def test_old_finished_session_is_unknown(stub_claude, tmp_path):
    import time

    old = int(time.time() * 1000) - 2 * 86400_000
    stub_claude.set_agents([agent(state="done", status="idle", waitingFor=None, pid=None, cwd=str(tmp_path), startedAt=old)])
    with pytest.raises(ActionError) as e:
        reply(stub_claude.cli(), "aaaa1111", "hi")
    assert e.value.code == "unknown_session"
    assert argvs(stub_claude) == [["agents", "--json", "--all"]]


def test_resume_timeout_after_stop_says_it_may_have_been_delivered(stub_claude, tmp_path):
    from beepy_gpt.host.claude_cli import ClaudeTimeout

    stub_claude.set_agents([agent(state="blocked", status="idle", waitingFor=None, cwd=str(tmp_path))])
    real = stub_claude.cli()

    class Backend:
        agents = staticmethod(real.agents)
        stop = staticmethod(real.stop)

        @staticmethod
        def resume_bg(*a, **k):
            raise ClaudeTimeout("claude --resume timed out")

    with pytest.raises(ActionError) as e:
        reply(Backend, "aaaa1111", "hi")
    assert e.value.code == "claude_error"
    assert e.value.message == (
        "session was stopped; the reply may or may not have been delivered (timed out)"
        " - check before resending"
    )
