import os
import subprocess
import sys

import pytest

from beepy_gpt import __version__
from beepy_gpt.client.cli import host_argv
from beepy_gpt.client.doctor import run_client_doctor
from beepy_gpt.config import ClientConfig, ConfigError
from helpers import FakeRun


def test_version():
    p = subprocess.run([sys.executable, "-m", "beepy_gpt.client.cli", "--version"], capture_output=True, text=True)
    assert p.stdout.strip() == f"bgpt {__version__}"


def test_host_argv():
    cfg = ClientConfig(ssh_target="user@workstation", ssh_options=["-p", "2222"])
    argv = host_argv(cfg, fake=False)
    assert argv[0] == "ssh" and argv[-3:] == ["user@workstation", "bgpt-host", "serve"]
    assert host_argv(ClientConfig(), fake=True)[1:] == ["-m", "beepy_gpt.host.cli", "serve", "--fake"]
    with pytest.raises(ConfigError):
        host_argv(ClientConfig(), fake=False)


class Dev:
    available = True

    def read_battery(self):
        return (63, 3.8)


class Wifi:
    name = "fake"


def test_client_doctor_all_ok():
    run = FakeRun()
    run.on(["ssh"], stdout="bgpt-host 0.1.0\n")
    lines = []
    rc = run_client_doctor(ClientConfig(ssh_target="user@workstation"), lines.append, run=run,
                           device=Dev(), wifi=Wifi(), term_size=lambda: os.terminal_size((50, 30)))
    assert rc == 0, lines
    assert run.calls[0][-2:] == ["bgpt-host", "--version"]


def test_client_doctor_reports_problems():
    run = FakeRun()
    lines = []
    rc = run_client_doctor(ClientConfig(), lines.append, run=run, device=None, wifi=None,
                           term_size=lambda: os.terminal_size((40, 20)))
    assert rc == 1
    text = "\n".join(lines)
    assert "ssh_target" in text and "40x20" in text
