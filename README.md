# beepy-gpt

Catch up on and steer your Claude Code sessions from a Beepy handheld (or any small terminal).

`bgpt` is a small curses client that runs on the device. `bgpt-host` is a helper on your
workstation that wraps the Claude Code CLI. Together they let you see which background sessions
are working, blocked or done, read what they did, reply to them, and approve or deny the tool
runs they ask permission for, all on a 50x30 screen with a thumb keyboard.

```
 workstation ●  2 need you wifi▂▄▆ 14:05 BAT 63%+
──────────────────────────────────────────────────
▶! parser        Refactor parser              perm
 ! demo          fork demo                 blocked
 * orbit         train sweep               working
 . notes         notes-app-12           RO    idle
 . fonts         fix loader with a ver…       done





















──────────────────────────────────────────────────
 ↵ open r reply a approve g refresh w wifi q quit
```

Both parts are stdlib-only Python with no runtime dependencies.

## How it works

```
Beepy (bgpt)                                    Workstation (bgpt-host)
+------------------------+   ssh <target>      +------------------------------+
| curses UI              |   bgpt-host serve   | serve (JSON-lines loop)      |
| state (pure reducer)   |<------------------->|  +- sessions   -> claude     |
| transport (ssh proc)   |  JSON lines, stdio  |  +- transcripts -> *.jsonl   |
| device (battery, LED)  |                     |  +- actions  -> stop/resume  |
| wifi (nmcli/wpa_cli)   |                     |  +- approvals -> spool dir   |
+------------------------+                     | hook <- PermissionRequest    |
                                               +------------------------------+
```

There is no daemon and no open port. The client starts `bgpt-host serve` over SSH, so SSH does
all of the authentication and encryption. When the connection drops, the client keeps showing the
last known state with an offline banner and reconnects on its own. A reply or decision made while
offline is not sent and says so ("not sent: ..."); an unsent reply stays open with its text so you
can send it again once the connection is back.

## Requirements

- Workstation: Linux, Claude Code with background sessions (`claude --bg`), Python 3.9+.
- Device: a Beepy (Pi Zero W or Zero 2 W) or any terminal of at least 50x30, Python 3.9+, and SSH
  key access to the workstation (Tailscale works well).

## Install

Workstation:

```
pipx install git+https://github.com/<you>/beepy-gpt
bgpt-host install-hook     # shows a diff of ~/.claude/settings.json and asks first
bgpt-host doctor
```

`install-hook` keeps symlinks and file modes of `settings.json`, keeps a unique backup of the old
file, and only ever touches its own hook entry. The hook timeout is set to
the host's hook timeout plus 30 seconds (`[hook] timeout_seconds` in `~/.config/beepy-gpt/host.ini`, default 600) so Claude Code never kills it before it has answered.

Device (set `[ui] ascii = true` in `client.ini` if the font lacks box-drawing characters or signal bars):

```
sudo apt install pipx      # or python3-pip
pipx install git+https://github.com/<you>/beepy-gpt
mkdir -p ~/.config/beepy-gpt
cp config/client.example.ini ~/.config/beepy-gpt/client.ini   # from a checkout, or copy it by hand
$EDITOR ~/.config/beepy-gpt/client.ini                        # set ssh_target = user@workstation
bgpt doctor
bgpt
```

SSH runs `bgpt-host` in a non-login shell, which may not have `~/.local/bin` (where pipx puts it)
on its `PATH`. If `bgpt doctor` reports that the host command was not found, set
`host_command = ~/.local/bin/bgpt-host` in the `[host]` section of `client.ini`.

## Working with sessions

- Start away-from-desk work with `claude --bg --permission-mode auto "..."`.
- For an interactive session, press Shift+Tab to switch it to auto mode if you want that, then
  type `/bg` before you leave.
- Sessions that are still interactive show up as read-only (`RO`).
- A reply stops the session and resumes it under the same ID. It is refused if the session started
  working again or disappeared, or if its working directory no longer exists
  ("working directory is missing"). If the stop worked but the resume failed, the message says
  "session was stopped but the reply was not sent: ..." so you know to retry.
- Permission prompts of background sessions are parked for the Beepy. For a session running in
  auto mode that means only the actions auto mode escalates; a session in another permission mode
  sends every prompt it would normally show. Interactive sessions keep prompting in their terminal.
- Requests that fail on the way are never resent automatically. "offline" means the request was
  not sent. "lost" means the connection dropped mid-request, so it may have been delivered:
  check the session before sending it again.
- Long commands on the approval screen are wrapped. A wrapped line ends with `↩` (`\` in ASCII
  mode) so a wrap cannot be mistaken for a real newline.

## Keys

The device only needs the arrow keys, Enter, Esc (Back), Backspace and printable characters.

| Screen | Keys |
| --- | --- |
| Sessions | Up/Down select, Enter open, `r` reply, `a` approve, `g` refresh, `q` quit (Esc does not quit here) |
| Session detail | Up/Down scroll, `r` reply, `a` approve, `G` jump to latest, Esc back |
| Approval | `y` allow, `n` deny (press twice to confirm), Enter deny with a note, Up/Down scroll, Esc back |
| Reply / deny note | type text, Enter send (confirm with a second Enter for a reply), Esc cancel |
| PIN | type digits, Enter ok, Esc cancel |
| Wi-Fi | Up/Down select, Enter join, `s` scan, `f` forget, `h` hidden network, Esc back |
| Wi-Fi password | type, Enter join, Up show/hide, Esc back |
| Any screen except text entry (reply, password, PIN) | `w` opens the Wi-Fi menu, also when offline |
| Wi-Fi result | `o` open a captive-portal login page, Esc back |

## Battery and LED

The battery percentage is the firmware's own percentage, smoothed over about a minute. The voltage
only feeds the `+` after it, a best-guess charging indicator based on the voltage rising. The LED flashes until you press a key when
something needs you.

## Wi-Fi

Press `w` on any screen except text entry (reply, password, PIN), even when offline, to scan, join, forget and add hidden networks. Both NetworkManager
and wpa_supplicant are supported and detected automatically. If joining is refused for permission
reasons, add your user to the `netdev` group (`sudo usermod -aG netdev $USER`, then log in again),
or for NetworkManager add a polkit rule that lets your user manage network connections. Captive
portals show a login URL that opens in `w3m` if it is installed.

## Security

- Anyone holding the unlocked device can approve tool runs.
- Use the optional PIN (`[security] pin`). It is asked before an approval opens and again after
  `pin_idle_minutes` without a keypress.
- Every request and decision is written to `~/.local/state/beepy-gpt/audit.log`.
- The hook never allows by default: any error, timeout or interactive session falls back to
  Claude Code's normal prompt. It waits 2 seconds past expiry for a late decision.
- The Wi-Fi password is passed to `nmcli` / `wpa_cli` on their command line, so other local users
  of the device can see it with `ps` while a connection attempt runs. Error messages never echo it.
- Remove everything the installer added with `bgpt-host uninstall-hook`.

## Autostart (optional)

On the Beepy, in `~/.bash_profile`:

```
[ "$(tty)" = /dev/tty1 ] && exec bgpt
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
