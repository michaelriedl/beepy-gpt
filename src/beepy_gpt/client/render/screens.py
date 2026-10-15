"""Every screen, drawn into a 50x30 Grid from AppState + the current View."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from beepy_gpt.client.render.grid import BOLD, COLS, NORMAL, REVERSE, Grid
from beepy_gpt.client.render.text import chunks, fit, wrap
from beepy_gpt.client.state import AppState, ApprovalView, SessionView
from beepy_gpt.client.wifi import signal_bars

BODY_TOP, BODY_ROWS = 2, 25
INFO_ROW, FOOTER_ROW = 27, 29
TEXT_SCREENS = {"reply", "deny_note", "pin", "wifi_password", "wifi_hidden"}
CONN = {"online": "●", "connecting": "○", "reconnecting": "○", "offline": "✕"}
HINTS = {
    "sessions": " ↵ open r reply a approve g refresh w wifi q quit",
    "detail": " ↑↓ scroll  r reply  a approve  G latest  Esc",
    "approval": " y allow  n deny  ↵ deny+note  ↑↓  Esc back",
    "deny_note": " ↵ deny with note  Esc back",
    "reply": " ↵ send  Esc cancel",
    "pin": " ↵ ok  Esc cancel",
    "wifi": " ↵ join  s scan  f forget  h hidden  Esc",
    "wifi_password": " ↵ join  ↑ show/hide  Esc",
    "wifi_hidden": " ↵ next  Esc",
    "wifi_result": " o open login page  Esc",
}


@dataclass
class View:
    screen: str
    selected: int = 0
    scroll: int = 0
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    ssid: Optional[str] = None
    text: str = ""
    reveal: bool = False
    confirm: Optional[str] = None
    message: Optional[str] = None
    hidden: bool = False


# --- shared pieces -------------------------------------------------------
def _status_bar(g: Grid, st: AppState, label: str, now: datetime, ascii: bool) -> None:
    need = f"  {st.need_count} need you" if st.need_count else ""
    wifi = None
    if st.wifi is not None:
        wifi = "wifi" + signal_bars(st.wifi.signal, ascii) if st.wifi.ssid else "wifi✕"
    bat = None
    if st.battery is not None:
        bat = f"BAT {st.battery.percent}%" + ("+" if st.battery.charging else "")
    parts = [("wifi", wifi), ("clock", now.strftime("%H:%M")), ("bat", bat)]
    left = f" {label} {CONN.get(st.connection, '✕')}"
    for drop in (None, "clock", "wifi"):
        if drop:
            parts = [(k, v) for k, v in parts if k != drop]
        right = " ".join(v for _, v in parts if v)
        if len(left) + len(need) + 1 + len(right) + 1 <= COLS:
            break
    room = COLS - len(need) - len(right) - 2
    if len(left) > room:
        left = fit(left, max(room, 4))
    g.put(0, 0, left, BOLD)
    g.put(0, len(left), need)
    col = COLS - len(right) - 1
    for key, value in parts:
        if not value:
            continue
        low = key == "bat" and st.battery is not None and st.battery.low
        g.put(0, col, value, REVERSE if low else NORMAL)
        col += len(value) + 1


def _info(g: Grid, st: AppState) -> None:
    # A notice answers the user's last action (e.g. "not sent: ..."), so it beats
    # the standing offline banner; it is cleared on the next key.
    if st.host_error:
        g.put(INFO_ROW, 0, fit(" " + st.host_error, COLS), REVERSE)
    elif st.notice:
        g.put(INFO_ROW, 0, fit(" " + st.notice, COLS))
    elif st.stale:
        g.put(INFO_ROW, 0, fit(" offline: showing last known state", COLS), BOLD)


def _lines_at(g: Grid, lines: list, top: int = BODY_TOP, rows: int = BODY_ROWS) -> None:
    for i, item in enumerate(lines[:rows]):
        text, attr = item if isinstance(item, tuple) else (item, NORMAL)
        g.put(top + i, 0, text, attr)


# --- sessions ------------------------------------------------------------
def session_row(s: SessionView, selected: bool) -> str:
    marker = "!" if s.needs_you else "*" if s.working else "."
    if s.needs_you:
        word = "perm" if s.waiting_for == "permission prompt" else "blocked"
    else:
        word = "working" if s.working else (s.state or s.status or "-")
    ro = "RO" if s.kind != "background" else "  "
    return f"{'▶' if selected else ' '}{marker} {fit(s.project, 13)} {fit(s.name, 22)} {ro} {word:>7.7}"


def _sessions(g: Grid, st: AppState, v: View) -> None:
    if not st.sessions:
        msg = "no Claude sessions" if st.connection == "online" else "connecting…"
        g.put(12, (COLS - len(msg)) // 2, msg)
        return
    start = max(0, v.selected - BODY_ROWS + 1)
    for i, s in enumerate(st.sessions[start:start + BODY_ROWS]):
        idx = start + i
        g.put(BODY_TOP + i, 0, session_row(s, idx == v.selected), REVERSE if idx == v.selected else NORMAL)


# --- detail --------------------------------------------------------------
def approval_summary(a: ApprovalView) -> str:
    if a.tool_name == "Bash":
        return "$ " + str(a.tool_input.get("command", "")).splitlines()[0] if a.tool_input.get("command") else "$"
    return a.description or a.tool_name


def feed_lines(feed) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for f in feed:
        if f.kind == "you":
            out += [(ln, BOLD) for ln in wrap("you: " + f.text, COLS, "  ")]
        elif f.kind == "claude":
            out += [(ln, NORMAL) for ln in wrap("claude: " + f.text, COLS, "  ")]
        elif f.kind == "tool_call":
            text = f.text if f.text.startswith("$ ") else "· " + f.text
            out += [(ln, NORMAL) for ln in wrap(text, COLS, "    ")]
        elif f.kind == "tool_result":
            out += [(ln, NORMAL) for ln in wrap(f"  {'✓' if f.ok else '✗'} {f.text}", COLS, "    ")]
        elif f.kind == "interrupted":
            out.append(("  ✗ interrupted", NORMAL))
        else:
            out.append((fit(f"? unknown entry ({f.text})", COLS), NORMAL))
    return out


def _detail(g: Grid, st: AppState, v: View) -> None:
    s = st.session(v.session_id)
    title = f"{s.project} · {s.name}" if s else "session no longer listed"
    if s and s.reply_block:
        title = fit(title, COLS - 5) + " [RO]"
    g.put(BODY_TOP, 0, fit(title, COLS), BOLD)
    top = BODY_TOP + 1
    a = st.approval_for_session(v.session_id)
    if a:
        g.put(top, 0, fit(f" ALLOW? {approval_summary(a)}", COLS - 4) + " a ▶", REVERSE)
        top += 1
    rows = BODY_TOP + BODY_ROWS - top
    lines = feed_lines(st.feed) if st.feed_session == v.session_id else [("loading…", NORMAL)]
    end = max(min(rows, len(lines)), len(lines) - v.scroll)
    _lines_at(g, lines[max(0, end - rows):end], top, rows)


# --- approval ------------------------------------------------------------
def approval_lines(a: ApprovalView, ascii: bool = False) -> list[str]:
    lines = [fit(f"session: {a.session_name or a.session_id[:8]}", COLS).rstrip()]
    if a.description:
        lines += wrap(a.description, COLS)
    lines.append("")
    if a.tool_name == "Bash":
        # The command first, then every other input (e.g. dangerouslyDisableSandbox):
        # the user must see the full input, never a subset. `description` is shown above.
        body = "$ " + str(a.tool_input.get("command", ""))
        for key, value in a.tool_input.items():
            if key not in ("command", "description"):
                shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                body += f"\n{key}: {shown}"
    else:
        body = json.dumps(a.tool_input, indent=1, ensure_ascii=False)
    mark = "\\" if ascii else "↩"
    for para in body.split("\n"):
        if len(para) <= COLS:
            lines.append(para)
        else:
            parts = chunks(para, COLS - 1)
            lines += [p + mark for p in parts[:-1]] + [parts[-1]]
    return lines


def _approval(g: Grid, st: AppState, v: View) -> None:
    a = st.approval(v.request_id)
    if a is None:
        g.put(BODY_TOP + 2, 0, "This request was answered or expired.")
        return
    g.put(BODY_TOP, 0, fit(f" ALLOW?  {a.tool_name} in {a.project}", COLS), REVERSE)
    lines = approval_lines(a, g.ascii)
    rows = BODY_ROWS - 1
    top = min(v.scroll, max(0, len(lines) - rows))
    _lines_at(g, lines[top:top + rows], BODY_TOP + 1, rows)
    # A host error / offline / notice line has priority on the info row, so "more below" yields to it.
    if top + rows < len(lines) and not (st.host_error or st.stale or st.notice):
        g.put(INFO_ROW, 0, fit(" ↓ more below", COLS), BOLD)


# --- text entry ----------------------------------------------------------
def _input(g: Grid, title: str, text: str, masked: bool) -> None:
    g.put(BODY_TOP, 0, fit(title, COLS), BOLD)
    shown = ("*" * len(text) if masked else text) + "▏"
    lines = chunks(shown, COLS)
    rows = BODY_ROWS - 2
    _lines_at(g, lines[-rows:], BODY_TOP + 2, rows)


def _reply(g: Grid, st: AppState, v: View) -> None:
    s = st.session(v.session_id)
    _input(g, f"Reply to {s.project} · {s.name}" if s else "Reply", v.text, False)


def _deny_note(g: Grid, st: AppState, v: View) -> None:
    _input(g, "Deny with a note for Claude:", v.text, False)


def _pin(g: Grid, st: AppState, v: View) -> None:
    _input(g, "Enter PIN for approvals", v.text, True)


def _wifi_password(g: Grid, st: AppState, v: View) -> None:
    _input(g, f"Password for {v.ssid}" + (" (empty = open)" if v.hidden else ""), v.text, not v.reveal)


def _wifi_hidden(g: Grid, st: AppState, v: View) -> None:
    _input(g, "Hidden network name", v.text, False)


# --- wifi ----------------------------------------------------------------
def _wifi(g: Grid, st: AppState, v: View) -> None:
    cur = st.wifi
    head = f"connected: {cur.ssid} {signal_bars(cur.signal, g.ascii)}" if cur and cur.ssid else "not connected"
    g.put(BODY_TOP, 0, "WI-FI", BOLD)
    g.put(BODY_TOP, COLS - len(head) - 1, head)
    if st.wifi_busy:
        g.put(BODY_TOP + 2, 1, "scanning…")
    rows = BODY_ROWS - 2
    start = max(0, v.selected - rows + 1)
    for j, n in enumerate(st.networks[start:start + rows]):
        i = start + j
        sel = i == v.selected
        row = (
            f"{'▶' if sel else ' '} {fit(n.ssid, 24)} {signal_bars(n.signal, g.ascii)} "
            f"{'WPA ' if n.secure else 'open'} {'saved' if n.saved else '     '}{'*' if n.active else ' '}"
        )
        g.put(BODY_TOP + 2 + j, 0, fit(row, COLS), REVERSE if sel else NORMAL)
    if st.wifi_error:
        g.put(INFO_ROW, 0, fit(" " + st.wifi_error, COLS), REVERSE)


def _wifi_result(g: Grid, st: AppState, v: View) -> None:
    g.put(BODY_TOP, 0, fit(f"Joining {v.ssid}", COLS), BOLD)
    if st.wifi_busy:
        g.put(BODY_TOP + 2, 1, "connecting…")
        return
    if st.wifi_error:
        _lines_at(g, wrap("Could not join: " + st.wifi_error, COLS), BODY_TOP + 2)
        return
    c = st.connectivity
    if c is None:
        return

    def mark(ok: Optional[bool]) -> str:
        return "n/a" if ok is None else "✓" if ok else "✗"

    lines = [
        f" IP address   {mark(bool(c.ip))} {c.ip or ''}",
        f" Internet     {mark(c.internet)}",
        f" Tailscale    {mark(c.tailscale)}",
    ]
    if c.captive_url:
        lines += ["", " Login page required:"] + wrap(c.captive_url, COLS - 2, "") + ["", " press o to open it in w3m"]
    _lines_at(g, lines, BODY_TOP + 2)


def _fatal(g: Grid, st: AppState) -> None:
    lines = wrap(st.fatal or "", COLS - 2)
    _lines_at(g, [(" " + ln, BOLD) for ln in lines], 8)
    g.put(FOOTER_ROW, 0, " q quit")


SCREENS: dict[str, Callable[[Grid, AppState, View], None]] = {
    "sessions": _sessions, "detail": _detail, "approval": _approval, "deny_note": _deny_note,
    "reply": _reply, "pin": _pin, "wifi": _wifi, "wifi_password": _wifi_password,
    "wifi_hidden": _wifi_hidden, "wifi_result": _wifi_result,
}


def render(st: AppState, v: View, label: str, now: datetime, ascii: bool = False) -> Grid:
    g = Grid(ascii=ascii)
    _status_bar(g, st, label, now, ascii)
    g.put(1, 0, "─" * COLS)
    g.put(28, 0, "─" * COLS)
    if st.fatal:
        _fatal(g, st)
        return g
    SCREENS[v.screen](g, st, v)
    if g.row_text(INFO_ROW).strip() == "":
        _info(g, st)
    if v.message:
        g.put(FOOTER_ROW, 0, fit(" " + v.message, COLS), REVERSE)
    else:
        hint = HINTS.get(v.screen, "")
        if v.screen == "detail":
            s = st.session(v.session_id)
            if s and s.reply_block:
                hint = hint.replace("  r reply", "")
        g.put(FOOTER_ROW, 0, hint)
    return g
