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
- The emulator's Wi-Fi controls are deferred, so the Wi-Fi menu is reached with `w` and uses fake
  networks that script the error paths:
  - joining `CoffeeShop` with the password `wrongpass` fails;
  - `Airport_Free` is a captive portal;
  - `Weak Signal` joins and then drops out.

## Screen rules

- 50 columns by 30 rows.
- NORMAL, BOLD and REVERSE attributes only.
- No emoji or wide characters.
- Snapshot tests live in `tests/golden/`. Regenerate them with
  `BGPT_UPDATE_GOLDEN=1 pytest tests/test_screens.py` and review the diff.

## Claude Code coupling

- `claude` is called only from `host/claude_cli.py`. A reply runs `claude --resume <id> --bg <text>`
  with no other flags, because any flag makes Claude Code fork a copy.
- Transcripts are parsed only in `host/transcripts.py`. The format is internal, so add fixtures when
  it changes.
- After Claude Code upgrades, re-verify the behaviors the host relies on:
  - `claude agents --json` lists sessions with their kind, state and working directory;
  - `claude --bg` starts a background session and prints its short ID;
  - `claude --resume <id> --bg <text>` continues a stopped session under the same ID, and any extra
    flag starts a copy instead;
  - the `PermissionRequest` hook receives the request on stdin and honors an allow or deny
    decision on stdout, and empty stdout with exit 0 falls back to the normal prompt;
  - auto mode only escalates some actions to the hook;
  - transcript files still use the line format that `host/transcripts.py` parses.

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
