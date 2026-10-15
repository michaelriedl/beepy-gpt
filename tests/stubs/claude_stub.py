"""Stand-in for the `claude` CLI used by tests. argv[1] is the stub's state dir."""

import json
import os
import sys

state, args = sys.argv[1], sys.argv[2:]


def path(name):
    return os.path.join(state, name)


def read(name, default=None):
    try:
        with open(path(name)) as f:
            return f.read()
    except FileNotFoundError:
        return default


with open(path("calls.log"), "a") as f:
    f.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")

code = int(read("exit_code", "0"))
if code:
    sys.stderr.write(read("stderr.txt", ""))
    sys.exit(code)

if args[:1] == ["agents"]:
    seq = json.loads(read("agents_seq.json", "[[]]"))
    n = int(read("agents_count", "0"))
    with open(path("agents_count"), "w") as f:
        f.write(str(n + 1))
    print(json.dumps(seq[min(n, len(seq) - 1)]))
elif args[:1] == ["--version"]:
    print("2.1.300 (Claude Code)")
elif args[:1] == ["stop"]:
    print(f"stopped {args[1]}")
elif "--resume" in args:
    sid = args[args.index("--resume") + 1]
    out = read("resume.txt")
    sys.stdout.write(out if out is not None else f"backgrounded · {sid[:8]}\n")
else:
    sys.stderr.write("stub: unsupported args\n")
    sys.exit(2)
