import queue
import sys
import time

from beepy_gpt.client.app import App
from beepy_gpt.client.device import NullDevice
from beepy_gpt.client.keys import DOWN, ENTER
from beepy_gpt.client.transport import Transport
from beepy_gpt.config import ClientConfig


def pump(app, events, cond, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            app.on_event(events.get(timeout=0.05))
        except queue.Empty:
            pass
        if cond():
            return True
    return False


def test_full_flow_against_fake_host():
    events = queue.Queue()
    t = Transport([sys.executable, "-m", "beepy_gpt.host.cli", "serve", "--fake"], events.put,
                  lambda s: events.put({"type": "connection", "status": s}))
    app = App(ClientConfig(), t.request, events.put, NullDevice())
    t.start()
    try:
        assert pump(app, events, lambda: app.state.sessions and app.state.approvals), "fake host sent sessions and an approval"
        assert app.state.sessions[0].id == "aaaa1111"

        for key in ("a", "y", "y"):
            app.on_key(key)
        assert pump(app, events, lambda: not app.state.approvals), "approval was not cleared after allow"

        idx = [s.id for s in app.state.sessions].index("dddd4444")
        for _ in range(idx):
            app.on_key(DOWN)
        app.on_key("r")
        for ch in "ship it":
            app.on_key(ch)
        app.on_key(ENTER)
        app.on_key(ENTER)
        assert pump(app, events, lambda: app.state.notice == "sent"), "reply was not accepted"

        app.on_key(ENTER)
        assert pump(app, events, lambda: any("(fake) received: ship it" in f.text for f in app.state.feed)), "fake host reply did not reach the feed"
    finally:
        t.stop()
