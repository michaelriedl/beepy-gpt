from beepy_gpt.client.app import App
from beepy_gpt.client.keys import BACK, BACKSPACE, DOWN, ENTER, UP
from beepy_gpt.config import ClientConfig
from beepy_gpt.client.wifi.fake import FakeWifi

S_BLOCKED = {"id": "aaaa1111", "session_id": "sid-a", "kind": "background", "name": "demo", "project": "proj",
             "state": "blocked", "status": "waiting", "waiting_for": "permission prompt", "needs_you": True,
             "working": False, "reply_block": None}
S_DONE = {**S_BLOCKED, "id": "dddd4444", "session_id": "sid-d", "state": "done", "status": "idle",
          "waiting_for": "", "needs_you": False}
S_INTER = {**S_DONE, "id": "cccc3333", "session_id": "sid-c", "kind": "interactive", "reply_block": "interactive"}
APPROVAL = {"request_id": "r1", "session_id": "sid-a", "project": "proj", "session_name": "demo",
            "tool_name": "Bash", "tool_input": {"command": "ls"}, "description": "", "expires_at": 9e9}


class Req:
    def __init__(self):
        self.sent = []

    def __call__(self, type_, callback=None, **fields):
        self.sent.append((type_, fields, callback))
        return len(self.sent)

    def types(self):
        return [t for t, _, _ in self.sent]


class Dev:
    def __init__(self):
        self.led = []

    def set_led_alert(self, on):
        self.led.append(on)


def make(clock, **cfg):
    req, dev = Req(), Dev()
    app = App(ClientConfig(**cfg), req, None, dev, wifi=FakeWifi(), checks=FakeWifi().checks,
              clock=clock, run_bg=lambda job: job(), which=lambda name: "/usr/bin/" + name)
    app.post = app.on_event
    app.on_event({"type": "connection", "status": "online"})
    app.on_event({"type": "sessions", "sessions": [S_BLOCKED, S_DONE, S_INTER]})
    app.on_event({"type": "approvals", "approvals": [APPROVAL]})
    return app, req, dev


def keys(app, *ks):
    for k in ks:
        app.on_key(k)


def test_open_detail_requests_feed(clock):
    app, req, _ = make(clock)
    keys(app, ENTER)
    assert app.view.screen == "detail" and req.sent[-1][:2] == ("feed", {"session_id": "sid-a"})
    req.sent[-1][2]({"type": "response", "ok": True, "events": [{"kind": "you", "text": "hi", "ok": None}]})
    assert app.state.feed[0].text == "hi"
    keys(app, BACK)
    assert app.view.screen == "sessions" and "close_feed" in req.types() and app.state.feed == ()


def test_reconnect_reopens_open_feed(clock):
    app, req, _ = make(clock)
    keys(app, ENTER)
    app.on_event({"type": "hello", "host_version": "0.1.0", "claude_version": "x", "claude_error": None})
    assert [t for t, _, _ in req.sent].count("feed") == 2
    assert req.sent[-1][:2] == ("feed", {"session_id": "sid-a"})


def test_reply_refused_for_interactive(clock):
    app, req, _ = make(clock)
    keys(app, DOWN, DOWN, "r")
    assert app.view.screen == "sessions" and "/bg" in app.view.message and req.sent == []


def test_reply_needs_two_enters_and_reports_offline(clock):
    app, req, _ = make(clock)
    keys(app, DOWN, "r", "h", "i", "x", BACKSPACE, ENTER)
    assert req.sent == [] and app.view.confirm == "send"
    keys(app, ENTER)
    assert req.sent[-1][:2] == ("reply", {"session_id": "sid-d", "text": "hi"})
    assert app.view.screen == "sessions"
    req.sent[-1][2]({"type": "response", "ok": False, "error": {"code": "offline", "message": "not connected; nothing was sent"}})
    assert app.state.notice == "not sent: not connected; nothing was sent"


def test_w_is_text_inside_reply(clock):
    app, _, _ = make(clock)
    keys(app, DOWN, "r", "w")
    assert app.view.screen == "reply" and app.view.text == "w"


def test_approval_double_press(clock):
    app, req, _ = make(clock)
    keys(app, "a", "y")
    assert req.sent == [] and app.view.message == "press y again to ALLOW"
    keys(app, "n")
    assert req.sent == [] and app.view.confirm == "n"
    keys(app, "n")
    assert req.sent[-1][:2] == ("decide", {"request_id": "r1", "behavior": "deny", "message": ""})
    assert app.view.screen == "sessions"


def test_deny_with_note(clock):
    app, req, _ = make(clock)
    keys(app, "a", ENTER, "l", "a", "t", "e", "r", ENTER)
    assert req.sent[-1][:2] == ("decide", {"request_id": "r1", "behavior": "deny", "message": "later"})


def test_pin_asked_before_approval_then_remembered_then_expires(clock):
    app, req, _ = make(clock, pin="1234", pin_idle_minutes=1)
    keys(app, "a")
    assert app.view.screen == "pin" and req.sent == []
    keys(app, "9", ENTER)
    assert app.view.message == "wrong PIN" and app.view.screen == "pin"
    keys(app, "1", "2", "3", "4", ENTER)
    assert app.view.screen == "approval"
    keys(app, "n", "n")  # deny is covered by the PIN too
    assert req.types() == ["decide"] and app.view.screen == "sessions"
    app.on_event({"type": "approvals", "approvals": []})  # host snapshot drops the decided request
    app.on_event({"type": "approvals", "approvals": [APPROVAL]})
    keys(app, "a", "y", "y")
    assert req.types() == ["decide", "decide"]
    clock.sleep(120)
    keys(app, "a")
    assert app.view.screen == "pin"


def test_pin_asked_again_if_it_times_out_on_the_approval_screen(clock):
    app, req, _ = make(clock, pin="1234", pin_idle_minutes=1)
    keys(app, "a", "1", "2", "3", "4", ENTER)
    assert app.view.screen == "approval"
    clock.sleep(120)
    keys(app, "y", "y")
    assert app.view.screen == "pin" and req.sent == []
    keys(app, "1", "2", "3", "4", ENTER)
    assert req.sent[-1][:2] == ("decide", {"request_id": "r1", "behavior": "allow", "message": ""})


def test_answered_approval_closes_view(clock):
    app, _, _ = make(clock)
    keys(app, "a")
    app.on_event({"type": "approvals", "approvals": []})
    keys(app, "y")
    assert app.view.screen == "sessions" and "answered" in app.view.message


def test_led_alerts(clock):
    app, _, dev = make(clock)
    assert dev.led == [True]
    app.on_event({"type": "sessions", "sessions": [S_BLOCKED, S_DONE, S_INTER]})
    assert dev.led == [True]
    app.on_event({"type": "connection", "status": "reconnecting"})
    assert dev.led == [True, False]


def test_led_disabled(clock):
    _, _, dev = make(clock, led_alerts=False)
    assert dev.led == []


def test_battery_sample(clock):
    app, _, _ = make(clock)
    app.on_event({"type": "battery_sample", "percent": 63, "volts": 3.8})
    assert app.state.battery.percent == 63


def test_wifi_join_secured_network(clock):
    app, _, _ = make(clock)
    keys(app, "w")
    assert app.view.screen == "wifi" and app.state.networks[0].ssid == "HomeNet"
    keys(app, DOWN, ENTER)
    assert app.view.screen == "wifi_password" and app.view.ssid == "CoffeeShop"
    keys(app, "w", "r", "o", "n", "g", "p", "a", "s", "s", UP)
    assert app.view.reveal and app.view.text == "wrongpass"
    keys(app, ENTER)
    assert app.view.screen == "wifi_result" and "wrong password" in app.state.wifi_error


def test_wifi_captive_portal_opens_w3m(clock):
    app, _, _ = make(clock)
    keys(app, "w")
    idx = [n.ssid for n in app.state.networks].index("Airport_Free")
    keys(app, *([DOWN] * idx), ENTER)
    assert app.state.connectivity.captive_url == "http://portal.example/login"
    keys(app, "o")
    assert app.external == ["w3m", "http://portal.example/login"]


def test_fatal_screen_quits(clock):
    app, _, _ = make(clock)
    app.on_event({"type": "fatal", "message": "protocol mismatch"})
    keys(app, "x")
    assert app.running
    keys(app, "q")
    assert not app.running


def test_quit(clock):
    app, _, _ = make(clock)
    keys(app, "q")
    assert not app.running


def test_reply_lost_is_not_called_not_sent(clock):
    from beepy_gpt.client.transport import LOST_MESSAGE

    app, req, _ = make(clock)
    keys(app, DOWN, "r", "h", "i", ENTER, ENTER)
    req.sent[-1][2]({"type": "response", "ok": False, "error": {"code": "lost", "message": LOST_MESSAGE}})
    assert app.state.notice == "reply: " + LOST_MESSAGE
    assert "not sent" not in app.state.notice
    assert req.types() == ["reply"]  # never auto-resent


def test_unknown_error_codes_render_their_message(clock):
    app, req, _ = make(clock)
    keys(app, "a", "y", "y")
    req.sent[-1][2]({"type": "response", "ok": False, "error": {"code": "internal", "message": "host exploded"}})
    assert app.state.notice == "host exploded"
    keys(app, DOWN, "r", "h", ENTER, ENTER)
    msg = "session was stopped but the reply was not sent: boom"
    req.sent[-1][2]({"type": "response", "ok": False, "error": {"code": "claude_error", "message": msg}})
    assert app.state.notice == msg


def test_reply_refused_in_detail_for_blocked_session(clock):
    app, req, _ = make(clock)
    keys(app, DOWN, DOWN, ENTER)
    assert app.view.screen == "detail"
    keys(app, "r")
    assert app.view.screen == "detail" and "/bg" in app.view.message


def test_wifi_scan_only_runs_through_run_bg(clock):
    app, _, _ = make(clock)
    jobs = []
    app.run_bg = jobs.append
    keys(app, "w")
    assert app.state.networks == () and len(jobs) == 1
    jobs.pop()()
    assert app.state.networks


def test_decide_offline_and_lost_notices(clock):
    from beepy_gpt.client.transport import LOST_MESSAGE, OFFLINE_MESSAGE

    app, req, _ = make(clock)
    keys(app, "a", "y", "y")
    req.sent[-1][2]({"type": "response", "ok": False, "error": {"code": "offline", "message": OFFLINE_MESSAGE}})
    assert app.state.notice == "not sent: " + OFFLINE_MESSAGE
    keys(app, "a", "y", "y")  # definitely unsent: retry allowed
    assert req.types().count("decide") == 2
    req.sent[-1][2]({"type": "response", "ok": False, "error": {"code": "lost", "message": LOST_MESSAGE}})
    assert app.state.notice == "decision: " + LOST_MESSAGE
    keys(app, "a")
    assert req.types().count("decide") == 2
    assert "answered" in app.view.message


def test_decided_request_not_resent_until_snapshot_drops_it(clock):
    app, req, _ = make(clock)
    keys(app, "a", "y", "y")
    req.sent[-1][2]({"type": "response", "ok": True})
    keys(app, "a")
    assert app.view.screen == "sessions" and "answered" in app.view.message
    assert req.types() == ["decide"]
    app.on_event({"type": "approvals", "approvals": []})
    app.on_event({"type": "approvals", "approvals": [APPROVAL]})
    keys(app, "a")
    assert app.view.screen == "approval"


def test_approval_scroll_clamped(clock):
    app, _, _ = make(clock)
    keys(app, "a", *([DOWN] * 50))
    top = app.view.scroll
    assert top < 50
    keys(app, UP)
    assert app.view.scroll == max(0, top - 1)


def test_unproducible_keys_ignored(clock):
    app, _, _ = make(clock, pin="1234", pin_idle_minutes=1)
    app.on_event({"type": "notice", "text": "hello"})
    keys(app, "TAB", "F5", "CTRL-C")
    assert app.state.notice == "hello" and app.running


def test_led_realerts_after_reconnect(clock):
    app, _, dev = make(clock)
    app.on_event({"type": "connection", "status": "reconnecting"})
    app.on_event({"type": "connection", "status": "online"})
    app.on_event({"type": "sessions", "sessions": [S_BLOCKED, S_DONE, S_INTER]})
    assert dev.led == [True, False, True]
