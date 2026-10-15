"""App controller: views stack, key handling, side effects. No curses in here."""

from __future__ import annotations

import hmac
import shutil
import threading
import time
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Optional

from beepy_gpt.client.battery import BatteryTracker
from beepy_gpt.client.keys import BACK, BACKSPACE, DOWN, ENTER, UP, beepy_producible
from beepy_gpt.client.render.grid import Grid
from beepy_gpt.client.render.screens import BODY_ROWS, TEXT_SCREENS, View, approval_lines, feed_lines, render
from beepy_gpt.client.transport import LOST_MESSAGE
from beepy_gpt.client.state import AppState, reduce
from beepy_gpt.client.wifi import PERMISSION_FIX, WifiError
from beepy_gpt.client.wifi.checks import run_checks
from beepy_gpt.host.sessions import REASON_TEXT


def _thread(job: Callable[[], None]) -> None:
    threading.Thread(target=job, daemon=True).start()


def _err_text(r: dict) -> str:
    return str((r.get("error") or {}).get("message", "failed"))


def _failure_text(prefix: str, r: dict) -> str:
    """Notice for a failed send. Only "offline" is known not to have been written."""
    code = (r.get("error") or {}).get("code")
    if code == "offline":
        return "not sent: " + _err_text(r)
    if code == "lost":
        # Written before the drop: it may have been delivered, so never say "not sent".
        return f"{prefix}: {LOST_MESSAGE}"
    return _err_text(r)


class App:
    def __init__(
        self,
        cfg: Any,
        request: Callable[..., Any],
        post: Optional[Callable[[dict], None]],
        device: Any,
        wifi: Any = None,
        checks: Optional[Callable[[Any], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        run_bg: Optional[Callable[[Callable[[], None]], None]] = None,
        which: Callable[[str], Optional[str]] = shutil.which,
    ):
        self.cfg = cfg
        self.request = request
        self.post = post
        self.device = device
        self.wifi = wifi
        self.checks = checks or run_checks
        self.clock = clock
        self.run_bg = run_bg or _thread
        self.which = which
        self.state = AppState()
        self.views = [View("sessions")]
        self.tracker = BatteryTracker(charge_rise_mv=cfg.charge_rise_mv)
        self.running = True
        self.external: Optional[list[str]] = None
        self._alerted: set = set()
        self._decided: set = set()
        self._pin_ok_until = float("-inf")
        self._after_pin: Optional[Callable[[], None]] = None

    @property
    def view(self) -> View:
        return self.views[-1]

    # --- events ---------------------------------------------------------
    def on_event(self, ev: dict) -> None:
        if ev.get("type") == "battery_sample":
            self.tracker.add(self.clock(), int(ev["percent"]), float(ev["volts"]))
            ev = {"type": "battery", "percent": self.tracker.percent,
                  "charging": self.tracker.charging, "low": self.tracker.low}
        prev = self.state
        self.state = reduce(self.state, ev)
        if ev.get("type") == "approvals":
            self._decided &= {a.request_id for a in self.state.approvals}
        if ev.get("type") == "connection" and self.state.connection != "online":
            self._alerted = set()
        self._update_led(prev)
        self._clamp()
        if ev.get("type") == "hello":
            # The first snapshot after a reconnect is authoritative: a delivered
            # decision is already absent from it, anything listed is undecided.
            self._decided.clear()
            self._reopen_feed()

    def _reopen_feed(self) -> None:
        # A reconnect starts a fresh host process with no open feed (spec §3.1).
        # The response replaces the feed with the last 200 events (no cursor).
        detail = next((v for v in reversed(self.views) if v.screen == "detail"), None)
        if detail is not None and detail.session_id is not None:
            self._request_feed(detail.session_id, report_errors=False)

    def _request_feed(self, sid: str, report_errors: bool) -> None:
        def cb(r: dict) -> None:
            if r.get("ok"):
                self.post({"type": "feed", "session_id": sid, "events": r.get("events", [])})
            elif report_errors:
                self._notice(_err_text(r))

        self.request("feed", cb, session_id=sid)

    def _update_led(self, prev: AppState) -> None:
        if not self.cfg.led_alerts:
            return
        if self.state.connection != "online":
            if prev.connection == "online":
                self.device.set_led_alert(False)
            return
        current = self.state.need_ids
        if current - self._alerted:
            self.device.set_led_alert(True)
        self._alerted = current

    def _clamp(self) -> None:
        for v in self.views:
            if v.screen == "sessions":
                v.selected = max(0, min(v.selected, len(self.state.sessions) - 1))
            elif v.screen == "wifi":
                v.selected = max(0, min(v.selected, len(self.state.networks) - 1))

    def render(self, now: datetime) -> Grid:
        return render(self.state, self.view, self.cfg.host_label, now, self.cfg.ascii)

    # --- helpers --------------------------------------------------------
    def _selected_session(self):
        ss = self.state.sessions
        return ss[self.view.selected] if ss and 0 <= self.view.selected < len(ss) else None

    def _notice(self, text: str) -> None:
        self.post({"type": "notice", "text": text})

    def _notice_on_error(self, r: dict) -> None:
        if not r.get("ok"):
            self._notice(_err_text(r))

    @staticmethod
    def _edit(v: View, key: str, max_len: int = 2000) -> bool:
        if key == BACKSPACE:
            v.text = v.text[:-1]
            v.confirm = None
            return True
        if len(key) == 1 and key.isprintable():
            if len(v.text) < max_len:
                v.text += key
            v.confirm = None
            return True
        return False

    # --- keys -----------------------------------------------------------
    def on_key(self, key: str) -> None:
        if not beepy_producible(key):
            return
        if self.cfg.pin and self.clock() < self._pin_ok_until:
            self._pin_ok_until = self.clock() + self.cfg.pin_idle_minutes * 60
        if self.state.notice:
            self.state = replace(self.state, notice=None)
        v = self.view
        v.message = None
        if self.state.fatal:
            if key in ("q", BACK):
                self.running = False
            return
        if key == "w" and v.screen not in TEXT_SCREENS and not v.screen.startswith("wifi") and self.wifi:
            self._open_wifi()
            return
        getattr(self, "_k_" + v.screen)(key)

    def _k_sessions(self, key: str) -> None:
        v = self.view
        s = self._selected_session()
        if key == UP:
            v.selected = max(0, v.selected - 1)
        elif key == DOWN:
            v.selected = min(max(0, len(self.state.sessions) - 1), v.selected + 1)
        elif key == ENTER and s:
            self._open_detail(s)
        elif key == "r" and s:
            self._start_reply(s)
        elif key == "a" and s:
            a = self.state.approval_for_session(s.session_id) or (self.state.approvals[0] if self.state.approvals else None)
            if a:
                self._open_approval(a)
        elif key == "g":
            self.request("refresh", self._notice_on_error)
        elif key == "q":
            self.running = False

    def _open_detail(self, s) -> None:
        self.views.append(View("detail", session_id=s.session_id))
        self._request_feed(s.session_id, report_errors=True)

    def _k_detail(self, key: str) -> None:
        v = self.view
        s = self.state.session(v.session_id)
        if key == UP:
            v.scroll = min(v.scroll + 1, max(0, len(feed_lines(self.state.feed)) - 1))
        elif key == DOWN:
            v.scroll = max(0, v.scroll - 1)
        elif key == "G":
            v.scroll = 0
        elif key == "r" and s:
            self._start_reply(s)
        elif key == "a":
            a = self.state.approval_for_session(v.session_id)
            if a:
                self._open_approval(a)
        elif key == BACK:
            self.views.pop()
            self.request("close_feed")
            self.post({"type": "feed_close"})

    def _start_reply(self, s) -> None:
        if s.reply_block:
            self.view.message = REASON_TEXT.get(s.reply_block, s.reply_block)
            return
        self.views.append(View("reply", session_id=s.session_id))

    def _k_reply(self, key: str) -> None:
        v = self.view
        if key == BACK:
            if v.confirm:
                v.confirm = None
            else:
                self.views.pop()
            return
        if self._edit(v, key):
            return
        if key == ENTER and v.text.strip():
            if v.confirm != "send":
                v.confirm = "send"
                v.message = "↵ again: stop+resume (attached views reset)"
                return
            sid, text = v.session_id, v.text

            def cb(r: dict) -> None:
                if r.get("ok"):
                    fork = r.get("forked_as")
                    self._notice("sent" + (f"; Claude continued it as a copy ({fork})" if fork else ""))
                else:
                    self._notice(_failure_text("reply", r))

            self.request("reply", cb, session_id=sid, text=text)
            self.views.pop()

    # --- approvals ------------------------------------------------------
    def _close_approval_views(self) -> None:
        while self.view.screen in ("approval", "deny_note", "pin"):
            self.views.pop()

    def _approval_gone(self) -> None:
        self._close_approval_views()
        self.view.message = "request already answered or expired"

    def _with_pin(self, fn: Callable[[], None]) -> None:
        # Spec §4.2/§5.5: a set PIN that has timed out is asked first.
        if self.cfg.pin and self.clock() >= self._pin_ok_until:
            self._after_pin = fn
            self.views.append(View("pin"))
            return
        fn()

    def _open_approval(self, a) -> None:
        if a.request_id in self._decided:
            self.view.message = "request already answered or expired"
            return
        self._with_pin(lambda: self.views.append(View("approval", request_id=a.request_id, session_id=a.session_id)))

    def _decide(self, a, behavior: str, message: str) -> None:
        def go() -> None:
            if a.request_id in self._decided:
                self._approval_gone()
                return

            def cb(r: dict) -> None:
                if r.get("ok"):
                    self._notice(f"{'allowed' if behavior == 'allow' else 'denied'}: {a.tool_name} in {a.project}")
                else:
                    if (r.get("error") or {}).get("code") != "lost":
                        self._decided.discard(a.request_id)  # definitely not applied: may retry
                    self._notice(_failure_text("decision", r))

            self._decided.add(a.request_id)
            self.request("decide", cb, request_id=a.request_id, behavior=behavior, message=message)
            self._close_approval_views()

        self._with_pin(go)

    def _k_approval(self, key: str) -> None:
        v = self.view
        a = self.state.approval(v.request_id)
        if a is None:
            self._approval_gone()
            return
        if key in ("y", "n"):
            if v.confirm == key:
                v.confirm = None
                self._decide(a, "allow" if key == "y" else "deny", "")
            else:
                v.confirm = key
                v.message = f"press {key} again to {'ALLOW' if key == 'y' else 'DENY'}"
            return
        v.confirm = None
        if key == ENTER:
            self.views.append(View("deny_note", request_id=a.request_id, session_id=a.session_id))
        elif key == UP:
            v.scroll = max(0, v.scroll - 1)
        elif key == DOWN:
            v.scroll = min(v.scroll + 1, max(0, len(approval_lines(a, self.cfg.ascii)) - (BODY_ROWS - 1)))
        elif key == BACK:
            self.views.pop()

    def _k_deny_note(self, key: str) -> None:
        v = self.view
        if key == BACK:
            self.views.pop()
            return
        if self._edit(v, key, 500):
            return
        if key == ENTER:
            a = self.state.approval(v.request_id)
            if a is None:
                self._approval_gone()
            else:
                self._decide(a, "deny", v.text.strip())

    def _k_pin(self, key: str) -> None:
        v = self.view
        if key == BACK:
            self.views.pop()
            self._after_pin = None
            return
        if self._edit(v, key, 32):
            return
        if key == ENTER:
            if hmac.compare_digest(v.text.encode(), self.cfg.pin.encode()):
                self._pin_ok_until = self.clock() + self.cfg.pin_idle_minutes * 60
                fn, self._after_pin = self._after_pin, None
                self.views.pop()
                if fn:
                    fn()
            else:
                v.text = ""
                v.message = "wrong PIN"

    # --- wifi -----------------------------------------------------------
    def _wifi_msg(self, e: WifiError) -> str:
        if e.code == "permission":
            return f"{e.message}. Fix: {PERMISSION_FIX.get(self.wifi.name, 'see README')}"
        return e.message

    def _open_wifi(self) -> None:
        self.views.append(View("wifi"))
        self._scan()

    def _scan(self) -> None:
        self.post({"type": "wifi_busy"})
        wifi = self.wifi

        def job() -> None:
            try:
                nets = wifi.scan()
                self.post({"type": "wifi_networks", "networks": nets})
                self.post({"type": "wifi_status", "status": wifi.status()})
            except WifiError as e:
                self.post({"type": "wifi_error", "message": self._wifi_msg(e)})

        self.run_bg(job)

    def _join(self, ssid: str, password: Optional[str], hidden: bool) -> None:
        self.views.append(View("wifi_result", ssid=ssid))
        self.post({"type": "wifi_busy"})
        wifi, checks = self.wifi, self.checks

        def job() -> None:
            try:
                wifi.connect(ssid, password, hidden)
                st = wifi.status()
                self.post({"type": "wifi_status", "status": st})
                self.post({"type": "connectivity", "result": checks(st)})
            except WifiError as e:
                self.post({"type": "wifi_error", "message": self._wifi_msg(e)})

        self.run_bg(job)

    def _forget(self, ssid: str) -> None:
        wifi = self.wifi

        def job() -> None:
            try:
                wifi.forget(ssid)
            except WifiError as e:
                self.post({"type": "wifi_error", "message": self._wifi_msg(e)})
                return
            self._scan()

        self.run_bg(job)

    def _k_wifi(self, key: str) -> None:
        v = self.view
        nets = self.state.networks
        if key == BACK:
            self.views.pop()
            return
        if key == UP:
            v.selected, v.confirm = max(0, v.selected - 1), None
        elif key == DOWN:
            v.selected, v.confirm = min(max(0, len(nets) - 1), v.selected + 1), None
        elif key == "s":
            self._scan()
        elif key == "h":
            self.views.append(View("wifi_hidden"))
        elif nets and 0 <= v.selected < len(nets):
            n = nets[v.selected]
            if key == ENTER:
                if n.secure and not n.saved:
                    self.views.append(View("wifi_password", ssid=n.ssid))
                else:
                    self._join(n.ssid, None, False)
            elif key == "f" and n.saved:
                if v.confirm == "f":
                    v.confirm = None
                    self._forget(n.ssid)
                else:
                    v.confirm = "f"
                    v.message = f"press f again to forget {n.ssid}"

    def _k_wifi_hidden(self, key: str) -> None:
        v = self.view
        if key == BACK:
            self.views.pop()
        elif not self._edit(v, key, 32) and key == ENTER and v.text.strip():
            self.views.append(View("wifi_password", ssid=v.text.strip(), hidden=True))

    def _k_wifi_password(self, key: str) -> None:
        v = self.view
        if key == BACK:
            self.views.pop()
            return
        if key == UP:
            v.reveal = not v.reveal
            return
        if self._edit(v, key, 63):
            return
        if key == ENTER and (v.text or v.hidden):
            ssid, password, hidden = v.ssid or "", v.text or None, v.hidden
            while self.view.screen in ("wifi_password", "wifi_hidden"):
                self.views.pop()
            self._join(ssid, password, hidden)

    def _k_wifi_result(self, key: str) -> None:
        if key == BACK:
            self.views.pop()
            self.post({"type": "connectivity", "result": None})
            return
        c = self.state.connectivity
        if key == "o" and c is not None and c.captive_url:
            if self.which("w3m"):
                self.external = ["w3m", c.captive_url]
            else:
                self.view.message = "install w3m to open the login page"
