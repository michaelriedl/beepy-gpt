import copy

import pytest

from beepy_gpt.client.state import MAX_FEED, AppState, BatteryView, reduce
from beepy_gpt.client.wifi import Network, WifiStatus

S1 = {"id": "aaaa1111", "session_id": "sid-a", "kind": "background", "name": "demo",
      "project": "proj", "state": "blocked", "status": "waiting", "waiting_for": "permission prompt",
      "needs_you": True, "working": False, "reply_block": None}
S2 = {**S1, "id": "bbbb2222", "session_id": "sid-b", "state": "working", "status": "",
      "waiting_for": "", "needs_you": False, "working": True, "reply_block": "working"}
A1 = {"request_id": "r1", "session_id": "sid-a", "cwd": "/home/dev/proj", "tool_name": "Bash",
      "tool_input": {"command": "ls"}, "description": "List", "created_at": 1.0, "expires_at": 9.0,
      "project": "proj", "session_name": "demo"}
A2 = {**A1, "request_id": "r2", "session_id": "sid-x"}
EV = {"kind": "you", "text": "hi", "ok": None}


def test_sessions_and_need_count():
    st = reduce(AppState(), {"type": "sessions", "sessions": [S1, S2]})
    assert [s.id for s in st.sessions] == ["aaaa1111", "bbbb2222"]
    assert st.need_count == 1
    st = reduce(st, {"type": "approvals", "approvals": [A1, A2]})
    assert st.need_count == 2  # sid-a counted once, sid-x adds one
    assert st.approvals[0].tool_input == {"command": "ls"}


def test_feed_open_append_close():
    st = reduce(AppState(), {"type": "feed", "session_id": "sid-a", "events": [EV]})
    st = reduce(st, {"type": "feed_append", "session_id": "sid-a", "events": [EV]})
    st = reduce(st, {"type": "feed_append", "session_id": "other", "events": [EV]})
    assert len(st.feed) == 2
    st = reduce(st, {"type": "feed_close"})
    assert st.feed_session is None and st.feed == ()


def test_feed_is_capped():
    st = reduce(AppState(), {"type": "feed", "session_id": "s", "events": [EV] * (MAX_FEED + 10)})
    assert len(st.feed) == MAX_FEED


def test_second_feed_event_replaces_feed():
    st = reduce(AppState(), {"type": "feed", "session_id": "s1", "events": [EV, EV]})
    st = reduce(st, {"type": "feed", "session_id": "s2", "events": [{"kind": "claude", "text": "yo"}]})
    assert st.feed_session == "s2"
    assert [ln.text for ln in st.feed] == ["yo"]


def test_feed_append_without_open_feed_is_ignored():
    st = AppState()
    assert reduce(st, {"type": "feed_append", "session_id": "s", "events": [EV]}) is st


def test_feed_event_without_session_id_is_ignored():
    st = reduce(AppState(), {"type": "feed", "session_id": "s", "events": [EV]})
    assert reduce(st, {"type": "feed", "events": [EV]}) is st
    assert reduce(AppState(), {"type": "feed", "session_id": None, "events": [EV]}).feed == ()


def test_feed_append_cap_applies():
    st = reduce(AppState(), {"type": "feed", "session_id": "s", "events": [EV] * MAX_FEED})
    st = reduce(st, {"type": "feed_append", "session_id": "s",
                     "events": [{"kind": "you", "text": "last"}] * 10})
    assert len(st.feed) == MAX_FEED
    assert st.feed[-1].text == "last"


def test_connection_and_stale():
    st = reduce(AppState(), {"type": "sessions", "sessions": [S1]})
    st = reduce(st, {"type": "connection", "status": "reconnecting"})
    assert st.stale
    assert not reduce(st, {"type": "connection", "status": "online"}).stale


def test_hello_errors_and_fatal():
    st = reduce(AppState(), {"type": "hello", "host_version": "0.1.0", "claude_version": "2.1",
                             "claude_error": None})
    assert st.host_version == "0.1.0" and st.host_error is None
    st = reduce(st, {"type": "host_error", "message": "Not logged in"})
    assert st.host_error == "Not logged in"
    assert reduce(st, {"type": "fatal", "message": "mismatch"}).fatal == "mismatch"


def test_battery():
    st = reduce(AppState(), {"type": "battery", "percent": 63, "charging": True, "low": False})
    assert st.battery == BatteryView(63, True, False)
    assert reduce(st, {"type": "battery", "percent": None}).battery is None


def test_wifi_events():
    st = reduce(AppState(), {"type": "wifi_busy"})
    assert st.wifi_busy
    st = reduce(st, {"type": "wifi_networks", "networks": [Network("A", 50, True)]})
    assert not st.wifi_busy and st.networks[0].ssid == "A"
    st = reduce(st, {"type": "wifi_error", "message": "denied"})
    assert st.wifi_error == "denied" and not st.wifi_busy
    st = reduce(st, {"type": "wifi_status", "status": WifiStatus("A", 50, "10.0.0.2")})
    assert st.wifi.ip == "10.0.0.2"


def test_unknown_event_is_ignored():
    st = AppState()
    assert reduce(st, {"type": "mystery"}) is st


def test_lookups():
    st = reduce(AppState(), {"type": "sessions", "sessions": [S1, S2]})
    st = reduce(st, {"type": "approvals", "approvals": [A1, A2]})
    assert st.session("sid-b").id == "bbbb2222" and st.session("nope") is None
    assert st.approval("r2").session_id == "sid-x" and st.approval(None) is None
    assert st.approval_for_session("sid-a").request_id == "r1"
    assert st.approval_for_session("sid-b") is None
    assert st.need_ids == {"sid-a", "sid-x"}


def test_empty_ids_are_not_counted_as_needs_you():
    st = reduce(AppState(), {"type": "sessions", "sessions": [{**S1, "session_id": ""}]})
    st = reduce(st, {"type": "approvals", "approvals": [{**A1, "session_id": ""}]})
    assert st.need_ids == frozenset()
    assert st.need_count == 0


MALFORMED = [
    {"type": "sessions", "sessions": None},
    {"type": "sessions", "sessions": [None, 1, "x"]},
    {"type": "sessions", "sessions": "abc"},
    {"type": "approvals", "approvals": None},
    {"type": "approvals", "approvals": ["x", None]},
    {"type": "approvals", "approvals": [{**A1, "expires_at": "soon"}]},
    {"type": "wifi_networks", "networks": None},
    {"type": "battery", "percent": "x", "charging": True, "low": False},
    {"type": "battery", "percent": float("nan")},
    {"type": "battery", "percent": float("inf")},
    {"type": "feed", "session_id": "s", "events": None},
    {"type": "feed", "session_id": "s", "events": "abc"},
    {"type": "feed", "session_id": "s", "events": [None, 3]},
    None,
    ["sessions"],
    "feed",
]


@pytest.mark.parametrize("ev", MALFORMED, ids=repr)
def test_malformed_events_never_raise(ev):
    assert isinstance(reduce(AppState(), ev), AppState)


def test_malformed_values_fall_back():
    st = reduce(AppState(), {"type": "approvals", "approvals": [{**A1, "expires_at": "soon"}]})
    assert st.approvals[0].expires_at == 0.0
    st = reduce(AppState(), {"type": "approvals", "approvals": [{**A1, "expires_at": float("inf")}]})
    assert st.approvals[0].expires_at == 0.0
    st = reduce(AppState(), {"type": "approvals", "approvals": [{**A1, "expires_at": None}]})
    assert st.approvals[0].expires_at == 0.0
    st = reduce(AppState(), {"type": "approvals", "approvals": [A1]})
    assert st.approvals[0].expires_at == 9.0
    st = reduce(AppState(), {"type": "battery", "percent": "x"})
    assert st.battery is None
    st = reduce(AppState(), {"type": "sessions", "sessions": [None, S1, 1]})
    assert [s.id for s in st.sessions] == ["aaaa1111"]
    st = reduce(AppState(), {"type": "wifi_networks", "networks": None})
    assert st.networks == () and not st.wifi_busy


def test_non_dict_event_returns_state_unchanged():
    st = AppState()
    assert reduce(st, None) is st
    assert reduce(st, ["sessions"]) is st


def test_reduce_does_not_mutate_inputs():
    base = reduce(AppState(), {"type": "sessions", "sessions": [S1]})
    base = reduce(base, {"type": "feed", "session_id": "s", "events": [EV]})
    cases = [
        {"type": "sessions", "sessions": [S1, S2]},
        {"type": "approvals", "approvals": [A1, A2]},
        {"type": "feed", "session_id": "t", "events": [EV, EV]},
        {"type": "feed_append", "session_id": "s", "events": [EV]},
        {"type": "battery", "percent": 40, "charging": False, "low": True},
    ]
    for ev in cases:
        state_before, ev_before = copy.deepcopy(base), copy.deepcopy(ev)
        reduce(base, ev)
        assert base == state_before
        assert ev == ev_before
