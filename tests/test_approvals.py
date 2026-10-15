import json
import stat

import pytest

from beepy_gpt.host.approvals import Spool, SpoolError

PAYLOAD = {
    "session_id": "sid-1",
    "cwd": "/home/dev/proj",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "touch b1.txt", "description": "Create b1"},
}


@pytest.fixture
def spool(tmp_path, clock):
    return Spool(tmp_path / "approvals", audit_log=tmp_path / "audit.log", clock=clock)


def test_create_and_pending(spool):
    req = spool.create(PAYLOAD, timeout=60)
    assert req.tool_name == "Bash" and req.description == "Create b1"
    assert req.expires_at - req.created_at == 60
    assert [r.request_id for r in spool.pending()] == [req.request_id]
    assert spool.get(req.request_id) == req


def test_spool_dir_is_private(spool):
    spool.create(PAYLOAD, timeout=60)
    assert stat.S_IMODE(spool.root.stat().st_mode) == 0o700


def test_decide_and_read(spool):
    req = spool.create(PAYLOAD, timeout=60)
    spool.decide(req.request_id, "allow")
    d = spool.read_decision(req.request_id)
    assert d["behavior"] == "allow" and d["message"] == ""
    assert spool.pending() == []


def test_second_decision_is_rejected(spool):
    req = spool.create(PAYLOAD, timeout=60)
    spool.decide(req.request_id, "deny", "no")
    with pytest.raises(SpoolError) as e:
        spool.decide(req.request_id, "allow")
    assert e.value.code == "already_decided"
    assert spool.read_decision(req.request_id)["behavior"] == "deny"
    assert not list(spool.root.glob("*.tmp"))


def test_expired_request(spool, clock):
    req = spool.create(PAYLOAD, timeout=10)
    clock.sleep(11)
    assert spool.pending() == []
    with pytest.raises(SpoolError) as e:
        spool.decide(req.request_id, "allow")
    assert e.value.code == "expired"


@pytest.mark.parametrize("rid,behavior,code", [("nope", "allow", "unknown_request"), (None, "maybe", "bad_request")])
def test_decide_errors(spool, rid, behavior, code):
    req = spool.create(PAYLOAD, timeout=60)
    with pytest.raises(SpoolError) as e:
        spool.decide(rid or req.request_id, behavior)
    assert e.value.code == code


def test_wait_decision_returns_when_decided(spool, clock):
    req = spool.create(PAYLOAD, timeout=60)

    def sleep(s):
        clock.sleep(s)
        if clock() > 1002:
            spool.decide(req.request_id, "allow")

    assert spool.wait_decision(req.request_id, timeout=60, poll=1, sleep=sleep)["behavior"] == "allow"


def test_wait_decision_times_out(spool, clock):
    req = spool.create(PAYLOAD, timeout=5)
    assert spool.wait_decision(req.request_id, timeout=5, poll=1, sleep=clock.sleep) is None


def test_corrupt_decision_ignored(spool):
    req = spool.create(PAYLOAD, timeout=60)
    (spool.root / f"{req.request_id}.decision").write_text('{"behavior": "yes"}')
    assert spool.read_decision(req.request_id) is None


def test_audit_log(spool, tmp_path):
    req = spool.create(PAYLOAD, timeout=60)
    spool.decide(req.request_id, "allow")
    lines = [json.loads(x) for x in (tmp_path / "audit.log").read_text().splitlines()]
    assert lines[-1]["event"] == "decision" and lines[-1]["behavior"] == "allow"


def test_cleanup_removes_request_and_decision_together(spool, clock):
    for _ in range(5):
        spool.decide(spool.create(PAYLOAD, timeout=60).request_id, "allow")
    clock.sleep(100_000)
    spool.cleanup(max_age=86400)
    assert list(spool.root.iterdir()) == []


def test_cleanup_keeps_recent_and_sweeps_orphans(spool):
    req = spool.create(PAYLOAD, timeout=60)
    orphan = spool.root / "999-dead.decision"
    orphan.write_text('{"behavior": "allow"}')
    spool.cleanup(max_age=86400)
    assert spool.get(req.request_id) == req and not orphan.exists()


def dead_pid():
    import subprocess
    import sys

    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_request_records_hook_pid(spool):
    import os

    req = spool.create(PAYLOAD, timeout=60, pid=os.getpid())
    assert spool.get(req.request_id).pid == os.getpid()
    assert "pid" not in req.to_wire()
    assert [r.request_id for r in spool.pending()] == [req.request_id]


def test_request_of_dead_hook_is_not_pending_and_cannot_be_decided(spool):
    req = spool.create(PAYLOAD, timeout=60, pid=dead_pid())
    assert spool.pending() == []
    with pytest.raises(SpoolError) as e:
        spool.decide(req.request_id, "allow")
    assert e.value.code == "expired"
    assert spool.read_decision(req.request_id) is None


def test_request_without_pid_behaves_as_before(spool, tmp_path):
    req = spool.create(PAYLOAD, timeout=60)
    path = spool.root / f"{req.request_id}.json"
    data = json.loads(path.read_text())
    data.pop("pid", None)  # a request written by an older hook
    path.write_text(json.dumps(data))
    assert [r.request_id for r in spool.pending()] == [req.request_id]
    spool.decide(req.request_id, "allow")
