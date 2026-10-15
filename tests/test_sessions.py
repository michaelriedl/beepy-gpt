from beepy_gpt.host.sessions import (
    find_session,
    from_agents,
    reply_block_reason,
    sort_sessions,
    to_wire,
)
from helpers import agent


def test_from_agents_normalizes():
    [s] = from_agents([agent(cwd="/home/dev/projects/parser")])
    assert s.id == "aaaa1111" and s.kind == "background"
    assert s.project == "parser" and s.waiting_for == "permission prompt"
    assert s.running and s.needs_you and not s.working


def test_interactive_without_id_gets_short_session_id():
    [s] = from_agents([agent(id="cccc3333", kind="interactive", state=None, status="idle", waitingFor=None)])
    assert s.id == "cccc3333" and s.kind == "interactive" and s.state == ""


def test_missing_kind_is_treated_as_interactive():
    rec = agent()
    del rec["kind"]
    assert from_agents([rec])[0].kind == "interactive"


def test_records_without_session_id_skipped():
    assert from_agents([{"id": "x"}, "junk"]) == []


def test_needs_you_and_working():
    blocked_idle = from_agents([agent(state="blocked", status="idle", waitingFor=None)])[0]
    working = from_agents([agent(state="working", status=None, waitingFor=None)])[0]
    done = from_agents([agent(state="done", status="idle", waitingFor=None)])[0]
    assert blocked_idle.needs_you and not blocked_idle.working
    assert working.working and not working.needs_you
    assert not done.needs_you and not done.working


def test_sort_order():
    raw = [
        agent(id="d0000000", state="done", status="idle", waitingFor=None, startedAt=5),
        agent(id="w0000000", state="working", status=None, waitingFor=None, startedAt=4),
        agent(id="b0000001", startedAt=1),
        agent(id="b0000002", startedAt=3),
    ]
    assert [s.id for s in sort_sessions(from_agents(raw))] == [
        "b0000002", "b0000001", "w0000000", "d0000000",
    ]


def test_find_by_either_id():
    sessions = from_agents([agent()])
    assert find_session(sessions, "aaaa1111") is sessions[0]
    assert find_session(sessions, sessions[0].session_id) is sessions[0]
    assert find_session(sessions, "nope") is None


def test_reply_block_reason():
    inter = from_agents([agent(kind="interactive")])[0]
    working = from_agents([agent(state="working", status=None, waitingFor=None)])[0]
    ok = from_agents([agent(state="done", status="idle", waitingFor=None)])[0]
    assert reply_block_reason(inter) == "interactive"
    assert reply_block_reason(working) == "working"
    assert reply_block_reason(ok) is None


def test_to_wire_keys():
    w = to_wire(from_agents([agent()])[0])
    assert set(w) == {
        "id", "session_id", "kind", "name", "project", "state", "status",
        "waiting_for", "needs_you", "working", "reply_block",
    }
    assert w["reply_block"] is None and w["needs_you"] is True


def test_reply_blocked_while_working_even_with_waiting_for():
    stale = from_agents([agent(state="working", status="waiting", waitingFor="permission prompt")])[0]
    assert reply_block_reason(stale) == "working"


def test_blocked_session_with_waiting_for_is_replyable():
    blocked = from_agents([agent(state="blocked", status="waiting", waitingFor="permission prompt")])[0]
    assert reply_block_reason(blocked) is None


def test_interactive_working_reports_interactive():
    inter = from_agents([agent(kind="interactive", state="working", status="working", waitingFor=None)])[0]
    assert reply_block_reason(inter) == "interactive"


def test_non_numeric_started_at_does_not_drop_the_list():
    got = from_agents([agent(startedAt="bad"), agent(id="bbbb2222", startedAt=5)])
    assert [s.started_at for s in got] == [0, 5]


def test_recent_keeps_running_or_recent_sessions():
    from beepy_gpt.host.sessions import RECENT_SECONDS, recent

    now = 2_000_000_000.0
    ms = int(now * 1000)
    got = recent(from_agents([
        agent(id="aaaa0001", pid=None, startedAt=ms - 1000),                        # recent, ms
        agent(id="aaaa0002", pid=None, startedAt=int(now) - 60),                    # recent, seconds
        agent(id="aaaa0003", pid=None, startedAt=ms - (RECENT_SECONDS + 60) * 1000),  # old, stopped
        agent(id="aaaa0004", pid=42, startedAt=ms - (RECENT_SECONDS + 60) * 1000),    # old but running
        agent(id="aaaa0005", pid=None, startedAt=None),                             # unknown age: kept
    ]), now=now)
    assert [s.id for s in got] == ["aaaa0001", "aaaa0002", "aaaa0004", "aaaa0005"]
    assert RECENT_SECONDS == 86400
