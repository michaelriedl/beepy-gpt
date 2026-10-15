import json
import os
import subprocess
import sys

from beepy_gpt import __version__
from beepy_gpt.config import HostConfig
from beepy_gpt.host.doctor import run_doctor
from beepy_gpt.host.install import plan_install
from beepy_gpt.protocol import encode


def isolated_env(tmp_path):
    # Never read the developer's real ~/.config/beepy-gpt/host.ini.
    return {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_STATE_HOME": str(tmp_path / "state")}


def test_version_flag():
    p = subprocess.run([sys.executable, "-m", "beepy_gpt.host.cli", "--version"], capture_output=True, text=True)
    assert p.stdout.strip() == f"bgpt-host {__version__}"


def test_serve_fake_speaks_protocol(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "beepy_gpt.host.cli", "serve", "--fake", "--exit-after", "1"],
        input=encode({"type": "hello", "id": 0}),
        capture_output=True, text=True, timeout=20, env=isolated_env(tmp_path),
    )
    msgs = [json.loads(line) for line in p.stdout.splitlines()]
    assert msgs[0]["type"] == "response" and msgs[0]["ok"] is True
    assert {"sessions", "approvals"} <= {m["type"] for m in msgs}


def test_install_hook_yes_then_uninstall(tmp_path):
    settings = tmp_path / "settings.json"
    base = [sys.executable, "-m", "beepy_gpt.host.cli"]
    env = isolated_env(tmp_path)
    subprocess.run(base + ["install-hook", "--yes", "--settings", str(settings)], check=True, capture_output=True, env=env)
    assert "PermissionRequest" in json.loads(settings.read_text())["hooks"]
    subprocess.run(base + ["uninstall-hook", "--yes", "--settings", str(settings)], check=True, capture_output=True, env=env)
    assert json.loads(settings.read_text()) == {}


def test_doctor_reports(stub_claude, tmp_path):
    settings = tmp_path / "settings.json"
    lines = []
    cfg = HostConfig(state_dir=tmp_path / "state")
    assert run_doctor(stub_claude.cli(), cfg, settings, lines.append) == 1
    assert any(line.startswith("[!!] PermissionRequest hook") for line in lines)
    settings.write_text(json.dumps(plan_install({}, "/x/bgpt-host hook", 630)))
    lines.clear()
    assert run_doctor(stub_claude.cli(), cfg, settings, lines.append) == 0
    assert all(line.startswith("[ok]") for line in lines)
