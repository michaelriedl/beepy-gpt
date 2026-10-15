from datetime import datetime

from beepy_gpt.client.render.grid import REVERSE
from beepy_gpt.client.render.screens import View, approval_lines, render, session_row
from beepy_gpt.client.state import AppState, reduce
from beepy_gpt.client.wifi import Network, WifiStatus
from beepy_gpt.client.wifi.checks import Connectivity
from helpers import assert_golden

NOW = datetime(2026, 1, 2, 14, 5)


def wire_session(id, project, name, state="done", status="idle", waiting="", needs=False,
                 working=False, kind="background", block=None):
    return {"id": id, "session_id": f"{id}-sid", "kind": kind, "name": name, "project": project,
            "state": state, "status": status, "waiting_for": waiting, "needs_you": needs,
            "working": working, "reply_block": block}


SESSIONS = [
    wire_session("aaaa1111", "parser", "Refactor parser", "blocked", "waiting", "permission prompt", needs=True),
    wire_session("eeee5555", "demo", "fork demo", "blocked", "idle", needs=True),
    wire_session("bbbb2222", "orbit", "train sweep", "working", "", working=True, block="working"),
    wire_session("cccc3333", "notes", "notes-app-12", "", "idle", kind="interactive", block="interactive"),
    wire_session("dddd4444", "fonts", "fix loader with a very long session name here"),
]
APPROVAL = {
    "request_id": "r1", "session_id": "aaaa1111-sid", "project": "parser", "session_name": "Refactor parser",
    "tool_name": "Bash", "description": "Run the parser tests", "expires_at": 9e9,
    "tool_input": {"command": "python -m pytest tests/test_parser.py --maxfail=1 -k 'tokenize or parse_header'"},
}
FEED = [
    {"kind": "you", "text": "Please work on the parser.", "ok": None},
    {"kind": "claude", "text": "Sure. Looking at the code first, then I will run the tests and report back.", "ok": None},
    {"kind": "tool_call", "text": "$ pytest -q", "ok": None},
    {"kind": "tool_result", "text": "12 passed in 1.02s", "ok": True},
    {"kind": "tool_call", "text": "Read /home/dev/projects/parser/README.md", "ok": None},
    {"kind": "tool_result", "text": "File not found", "ok": False},
    {"kind": "interrupted", "text": "interrupted", "ok": None},
    {"kind": "unknown", "text": "widget", "ok": None},
]


def base_state(**over):
    st = AppState(connection="online")
    st = reduce(st, {"type": "sessions", "sessions": SESSIONS})
    st = reduce(st, {"type": "approvals", "approvals": [APPROVAL]})
    st = reduce(st, {"type": "battery", "percent": 63, "charging": True, "low": False})
    st = reduce(st, {"type": "wifi_status", "status": WifiStatus("HomeNet", 82, "192.168.4.20")})
    for k, v in over.items():
        st = reduce(st, {"type": k, **v})
    return st


def test_status_bar_full():
    g = render(base_state(), View("sessions"), "workstation", NOW)
    assert g.row_text(0).rstrip() == " workstation ●  2 need you wifi▂▄▆ 14:05 BAT 63%+"


def test_status_bar_drops_clock_then_wifi():
    g = render(base_state(), View("sessions"), "a-much-longer-label!", NOW)
    row = g.row_text(0)
    assert "14:05" not in row and "wifi" not in row and row.rstrip().endswith("BAT 63%+")
    assert len(row) == 50


def test_low_battery_is_reverse():
    st = base_state(battery={"percent": 9, "charging": False, "low": True})
    g = render(st, View("sessions"), "w", NOW)
    col = g.row_text(0).index("BAT")
    assert g.attr(0, col) == REVERSE


def test_session_row_layout():
    st = base_state()
    row = session_row(st.sessions[0], selected=True)
    assert row == "▶! parser" + " " * 8 + "Refactor parser" + " " * 14 + "perm"
    assert len(session_row(st.sessions[4], selected=False)) == 50
    assert "RO" in session_row(st.sessions[3], selected=False)


def test_long_command_fully_reachable():
    cmd = "echo " + " ".join(f"arg{i}" for i in range(120)) + "\nsecond line ✓"
    a = reduce(AppState(), {"type": "approvals", "approvals": [{**APPROVAL, "tool_input": {"command": cmd}}]}).approvals[0]
    lines = approval_lines(a)
    assert all(len(line) <= 50 for line in lines)
    assert "".join(lines).replace(" ", "").endswith(cmd.replace(" ", "").replace("\n", ""))
    st = base_state(approvals={"approvals": [{**APPROVAL, "tool_input": {"command": cmd}}]})
    g = render(st, View("approval", request_id="r1", scroll=10_000), "w", NOW)
    body = "".join(g.row_text(r) for r in range(2, 27))
    assert "second line" in body


def test_fatal_screen():
    st = base_state(fatal={"message": "protocol mismatch (client 1, host 2). Upgrade beepy-gpt on both machines."})
    text = "\n".join(render(st, View("sessions"), "w", NOW).row_text(r) for r in range(30))
    assert "protocol mismatch" in text and "q quit" in text


def test_goldens():
    feed_state = base_state(feed={"session_id": "aaaa1111-sid", "events": FEED})
    nets = [Network("HomeNet", 82, True, True, True), Network("CoffeeShop", 61, True), Network("Airport_Free", 45, False)]
    cases = {
        "sessions": (base_state(), View("sessions")),
        "sessions_offline_stale": (base_state(connection={"status": "reconnecting"}), View("sessions", selected=2)),
        "sessions_empty_connecting": (AppState(), View("sessions")),
        "detail": (feed_state, View("detail", session_id="aaaa1111-sid")),
        "approval": (base_state(), View("approval", request_id="r1")),
        "approval_confirm": (base_state(), View("approval", request_id="r1", confirm="y", message="press y again to ALLOW")),
        "reply": (base_state(), View("reply", session_id="dddd4444-sid", text="please also update the changelog")),
        "deny_note": (base_state(), View("deny_note", request_id="r1", text="not now")),
        "pin": (base_state(), View("pin", text="12")),
        "wifi": (base_state(wifi_networks={"networks": nets}), View("wifi", selected=1)),
        "wifi_password": (base_state(), View("wifi_password", ssid="CoffeeShop", text="secret")),
        "wifi_result_captive": (
            base_state(connectivity={"result": Connectivity("192.168.4.20", False, "http://portal.example/login", None)}),
            View("wifi_result", ssid="Airport_Free"),
        ),
        "host_error": (base_state(host_error={"message": "claude agents failed: Not logged in"}), View("sessions")),
    }
    for name, (st, view) in cases.items():
        assert_golden(name, render(st, view, "workstation", NOW))
    assert_golden("sessions_ascii", render(base_state(), View("sessions"), "workstation", NOW, ascii=True))
