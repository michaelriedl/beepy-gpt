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
    cmd = "echo " + " ".join(f"arg{i}" for i in range(120)) + " 日本\nsecond line ✓"
    a = reduce(AppState(), {"type": "approvals", "approvals": [{**APPROVAL, "tool_input": {"command": cmd}}]}).approvals[0]
    lines = approval_lines(a)
    assert all(len(line) <= 50 for line in lines)
    assert "".join(lines).replace("↩", "").replace(" ", "").endswith(cmd.replace(" ", "").replace("\n", ""))
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


def _appr(**over):
    return reduce(AppState(), {"type": "approvals", "approvals": [{**APPROVAL, **over}]}).approvals[0]


def test_wrapped_line_differs_from_real_newline():
    wrapped = _appr(tool_input={"command": "echo " + "x" * 43 + "rm -rf ~"})
    newline = _appr(tool_input={"command": "echo " + "x" * 43 + "\nrm -rf ~"})
    lw, ln = approval_lines(wrapped), approval_lines(newline)
    assert lw != ln
    assert any(line.endswith("↩") for line in lw) and not any(line.endswith("↩") for line in ln)
    assert all(len(line) <= 50 for line in lw)
    assert "".join(line.rstrip("↩") for line in lw[-2:]).endswith("echo " + "x" * 43 + "rm -rf ~")
    assert any(line.endswith("\\") for line in approval_lines(wrapped, ascii=True))


def test_session_line_fitted():
    a = _appr(session_name="n" * 80)
    assert len(approval_lines(a)[0]) <= 50


def _feed_state(n):
    ev = [{"kind": "claude", "text": f"line {i}", "ok": None} for i in range(n)]
    return base_state(feed={"session_id": "aaaa1111-sid", "events": ev})


def test_detail_scroll_is_clamped():
    st = _feed_state(3)
    for sc in (3, 50):
        body = "".join(render(st, View("detail", session_id="aaaa1111-sid", scroll=sc), "w", NOW).row_text(r) for r in range(2, 27))
        assert "line 2" in body and "line 0" in body


def test_wifi_selected_visible_beyond_window():
    nets = [Network(f"net{i:02d}", 50, True) for i in range(30)]
    st = base_state(wifi_networks={"networks": nets})
    g = render(st, View("wifi", selected=28), "w", NOW)
    rows = [r for r in range(30) if "net28" in g.row_text(r)]
    assert rows and g.attr(rows[0], 0) == REVERSE


def test_detail_read_only_cue():
    st = base_state(feed={"session_id": "cccc3333-sid", "events": []})
    g = render(st, View("detail", session_id="cccc3333-sid"), "w", NOW)
    assert "[RO]" in g.row_text(2) and "r reply" not in g.row_text(29)
    g = render(base_state(feed={"session_id": "dddd4444-sid", "events": []}), View("detail", session_id="dddd4444-sid"), "w", NOW)
    assert "[RO]" not in g.row_text(2) and "r reply" in g.row_text(29)


def test_notice_beats_more_below_on_approval():
    cmd = "\n".join(f"line {i}" for i in range(60))
    st = base_state(approvals={"approvals": [{**APPROVAL, "tool_input": {"command": cmd}}]})
    assert "more below" in render(st, View("approval", request_id="r1"), "w", NOW).row_text(27)
    st = reduce(st, {"type": "host_error", "message": "claude agents failed"})
    row = render(st, View("approval", request_id="r1"), "w", NOW).row_text(27)
    assert "claude agents failed" in row
    st = reduce(reduce(st, {"type": "host_error", "message": ""}), {"type": "connection", "status": "reconnecting"})
    st = reduce(st, {"type": "host_error", "message": ""})
    assert "offline" in render(st, View("approval", request_id="r1"), "w", NOW).row_text(27)


def test_bash_approval_shows_every_input_key():
    a = reduce(AppState(), {"type": "approvals", "approvals": [{**APPROVAL, "tool_input": {
        "command": "rm -rf build", "description": "Clean", "dangerouslyDisableSandbox": True,
        "timeout": 600000, "run_in_background": False, "note": "x" * 80,
    }}]}).approvals[0]
    lines = approval_lines(a)
    assert "$ rm -rf build" in lines
    assert "dangerouslyDisableSandbox: true" in lines
    assert "timeout: 600000" in lines and "run_in_background: false" in lines
    assert not any(line.startswith("description:") or line.startswith("command:") for line in lines)
    note = [i for i, line in enumerate(lines) if line.startswith("note: ")][0]
    assert lines[note].endswith("↩") and (lines[note][:-1] + lines[note + 1]) == "note: " + "x" * 80


def test_notice_beats_stale_banner():
    st = base_state(connection={"status": "reconnecting"})
    assert "offline" in render(st, View("sessions"), "w", NOW).row_text(27)
    st = reduce(st, {"type": "notice", "text": "not sent: not connected"})
    assert "not sent: not connected" in render(st, View("sessions"), "w", NOW).row_text(27)
