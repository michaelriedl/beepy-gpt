"""Fake `bgpt-host serve` for transport tests. argv: <log file> <mode: ok|drop|mismatch|unicode|internal>."""

import json
import sys

log, mode = sys.argv[1], sys.argv[2]
sys.stdout.reconfigure(encoding="utf-8")


def send(msg):
    msg["v"] = 1
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    with open(log, "a") as f:
        f.write(json.dumps(msg) + "\n")
    if msg["type"] == "hello":
        if mode == "mismatch":
            send({"type": "response", "id": msg["id"], "ok": False,
                  "error": {"code": "protocol_mismatch", "message": "client protocol 1, host protocol 2"}})
            continue
        send({"type": "response", "id": msg["id"], "ok": True, "host_version": "9.9.9",
              "protocol": 1, "claude_version": "x", "claude_error": None})
        send({"type": "sessions", "sessions": []})
        if mode == "unicode":  # U+2028 / U+2029 / U+0085 must not split a line
            send({"type": "note", "text": "a\u2028b\u2029c\u0085d"})
    elif msg["type"] == "reply" and mode == "drop":
        sys.exit(0)  # die without answering, like a dropped ssh connection
    elif mode == "internal":
        send({"type": "response", "id": msg["id"], "ok": False,
              "error": {"code": "internal", "message": "boom"}})
    else:
        send({"type": "response", "id": msg["id"], "ok": True})
