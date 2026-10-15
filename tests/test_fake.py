import pytest

from beepy_gpt.host.approvals import Spool
from beepy_gpt.host.fake import FakeClaude
from beepy_gpt.host.sessions import find_session, from_agents
from beepy_gpt.host.transcripts import read_events


def make(tmp_path, clock):
    spool = Spool(tmp_path / "approvals", clock=clock)
    return FakeClaude(tmp_path, spool, clock=clock), spool


def test_scripted_sessions_and_approval(tmp_path, clock):
    fake, spool = make(tmp_path, clock)
    sessions = from_agents(fake.agents())
    assert {s.id for s in sessions} == {"aaaa1111", "bbbb2222", "cccc3333", "dddd4444", "eeee5555"}
    assert find_session(sessions, "cccc3333").kind == "interactive"
    [req] = spool.pending()
    assert req.tool_name == "Bash" and req.session_id.startswith("aaaa1111")


def test_working_session_finishes(tmp_path, clock):
    fake, _ = make(tmp_path, clock)
    assert find_session(from_agents(fake.agents()), "bbbb2222").working
    clock.sleep(21)
    assert find_session(from_agents(fake.agents()), "bbbb2222").state == "done"


def test_reply_appends_to_transcript(tmp_path, clock):
    fake, _ = make(tmp_path, clock)
    s = find_session(from_agents(fake.agents()), "dddd4444")
    before, _ = read_events(fake.transcript_for(s))
    fake.stop("dddd4444")
    res = fake.resume_bg(s.session_id, "hello", s.cwd)
    after, _ = read_events(fake.transcript_for(s))
    assert res.forked_as is None
    assert [e.text for e in after[len(before):]] == ["hello", "(fake) received: hello"]


def test_fork_demo(tmp_path, clock):
    fake, _ = make(tmp_path, clock)
    s = find_session(from_agents(fake.agents()), "eeee5555")
    assert fake.resume_bg(s.session_id, "x", s.cwd).forked_as == "f0f0f0f0"


def test_reply_through_actions_and_server(tmp_path, clock):
    from beepy_gpt.host.actions import ActionError, reply

    fake, spool = make(tmp_path, clock)
    assert reply(fake, "dddd4444", "hello") == {"forked_as": None}
    s = find_session(from_agents(fake.agents()), "dddd4444")
    events, _ = read_events(fake.transcript_for(s))
    assert events[-1].text == "(fake) received: hello"
    assert reply(fake, "eeee5555", "x") == {"forked_as": "f0f0f0f0"}
    with pytest.raises(ActionError):
        reply(fake, "bbbb2222", "go on")  # still working
