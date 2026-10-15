# Contributing

## Setup

```
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

## Run without hardware

- `bgpt --emulate` runs the client against a fake device and fake host. It needs a terminal of at
  least 80x32.
- In the emulator, F5/F6 change the battery voltage and F7 toggles charging.
- Keys the Beepy cannot type (Tab, Ctrl, function keys) are refused on purpose.
- `bgpt-host serve --fake` provides scripted sessions whose working directories are real temporary
  directories. Add `--exit-after SECONDS` to simulate a dropped connection; the client reconnects.
- The emulator's side panel has no Wi-Fi controls yet (F5-F7 are taken). The Wi-Fi menu itself
  works: press `w`, and it runs against the fake backend, whose networks script the error paths:
  - joining `CoffeeShop` with the password `wrongpass` fails;
  - `Airport_Free` is a captive portal;
  - `Weak Signal` joins and then drops out.

## Screen rules

- 50 columns by 30 rows.
- NORMAL, BOLD and REVERSE attributes only.
- No emoji or wide characters.
- Snapshot tests live in `tests/golden/`. Regenerate them with
  `BGPT_UPDATE_GOLDEN=1 .venv/bin/pytest tests/test_screens.py` and review the diff.

## Claude Code coupling

- `claude` is called only from `host/claude_cli.py`. A reply runs `claude --resume <id> --bg <text>`
  with no other flags, because any flag makes Claude Code fork a copy.
- Transcripts are parsed only in `host/transcripts.py`. The format is internal, so add fixtures when
  it changes.
- Re-verify these behaviors after Claude Code upgrades (last checked on Claude Code 2.1.300):
  1. `claude agents --json` is the documented way to read session state. It lists `kind: background`
     and `kind: interactive` sessions with `state`, `status`, `waitingFor`, `sessionId`, `id`
     (short), `name` and `cwd`; `--all` includes finished background sessions.
  2. `claude --resume <id> --bg "msg"` on a running session starts a copy with a new ID and leaves
     the original untouched.
  3. The same command on a stopped session continues it under the same ID, with its saved options.
  4. Passing any flag on resume (for example `--permission-mode auto`) starts a copy.
  5. `claude stop <id>` records any in-flight tool call as interrupted; the transcript stays
     consistent.
  6. A `PermissionRequest` hook gets JSON on stdin (`session_id`, `transcript_path`, `cwd`,
     `permission_mode`, `tool_name`, `tool_input`, ...) and can answer with
     `{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior":
     "allow" | "deny", "message": "..."}}}`. An allow runs the tool; a deny passes the message back
     to the model. While the hook waits, `agents --json` shows `waitingFor: "permission prompt"`.
  7. Background sessions have `CLAUDE_JOB_DIR` set and `CLAUDE_CODE_SESSION_ATTENDED=0`;
     interactive ones have it empty and `1`. This is undocumented, so always cross-check with
     `kind` from `agents --json`.
  8. Interactive sessions show the terminal prompt while the hook runs, so the hook must exit
     immediately for them.
  9. `--settings` is not carried to copies or wakes, so the hook lives in user settings.
  10. `claude logs <id>` is a raw terminal stream (unusable for the feed). Transcript JSONL parses
      cleanly but is an internal format that may change.
  11. Auto mode works for background sessions (`--permission-mode auto`): routine actions run with
      no prompt and no hook call.
  12. Interactive sessions can be backgrounded from inside with `/bg` (or `/background`), or Left
      on an empty prompt. No shell command does this from outside.
- Still unverified (test on a real setup):
  - whether a hook timeout falls back to Claude Code's normal behavior;
  - whether `/bg` keeps the session's current permission mode;
  - what auto mode does with actions it considers risky (escalate to the hook, or deny outright).
    The design handles both.
- By our own design (not a Claude Code guarantee), the hook never allows by default: any error,
  timeout or interactive session makes it exit 0 with empty stdout.

## Privacy

Never commit real hostnames, usernames, IPs, keys or session content. Fixtures use `/home/dev/...`
and made-up text; docs and examples use placeholders such as `user@workstation`. CI runs gitleaks.

## On-device checklist

Run before a release, on a Pi Zero W if possible.

- [ ] Display renders 50x30 and there are no characters the font can't show.
- [ ] Keys: Back = Esc, touchpad gives arrows and Enter, Berry-mode arrows work.
- [ ] The battery percentage matches `/sys/firmware/beepy/battery_percent` within 2%, and `+` appears within about 3 minutes of plugging in.
- [ ] The LED flashes on a new approval and stops on a keypress.
- [ ] Wi-Fi: scan, join a WPA network, join an open network, a wrong password gives an error, forget works.
- [ ] Speed on the Zero W: a screen change takes under 150 ms. Use a stopwatch over 20 changes.
- [ ] SSH drop (toggle Wi-Fi): `○`, a stale banner, writes are disabled, and it reconnects.
