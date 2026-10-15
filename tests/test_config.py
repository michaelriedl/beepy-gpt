from pathlib import Path

import pytest

from beepy_gpt.config import (
    ClientConfig,
    ConfigError,
    HostConfig,
    config_dir,
    load_client_config,
    load_host_config,
    state_dir,
)

ROOT = Path(__file__).resolve().parents[1]


def test_xdg_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    assert config_dir() == tmp_path / "c" / "beepy-gpt"
    assert state_dir() == tmp_path / "s" / "beepy-gpt"


def test_missing_files_give_defaults(tmp_path):
    host = load_host_config(tmp_path / "nope.ini")
    client = load_client_config(tmp_path / "nope.ini")
    assert host.hook_timeout_seconds == 600 and host.agents_poll_seconds == 3.0
    assert client == ClientConfig()


def test_client_values_parsed(tmp_path):
    p = tmp_path / "client.ini"
    p.write_text(
        "[host]\nssh_target = me@box\nssh_options = -p 2222 -o Foo=bar\nlabel = box\n"
        "[ui]\nascii = yes\n[device]\nled_alerts = off\ncharge_rise_mv = 20\n"
        "[wifi]\ninterface = wlan1\n[security]\npin = 1234\npin_idle_minutes = 5\n"
    )
    c = load_client_config(p)
    assert c.ssh_target == "me@box"
    assert c.ssh_options == ["-p", "2222", "-o", "Foo=bar"]
    assert c.host_label == "box" and c.ascii is True and c.led_alerts is False
    assert c.charge_rise_mv == 20 and c.wifi_interface == "wlan1"
    assert c.pin == "1234" and c.pin_idle_minutes == 5


def test_host_values_parsed(tmp_path):
    p = tmp_path / "host.ini"
    p.write_text("[hook]\ntimeout_seconds = 30\n[state]\ndir = ~/bgpt-state\n")
    h = load_host_config(p)
    assert h.hook_timeout_seconds == 30
    assert h.state_dir == Path("~/bgpt-state").expanduser()


@pytest.mark.parametrize("body", ["[hook]\ntimeout_seconds = soon\n", "[poll]\nagents_seconds = x\n"])
def test_invalid_host_value(tmp_path, body):
    p = tmp_path / "host.ini"
    p.write_text(body)
    with pytest.raises(ConfigError):
        load_host_config(p)


def test_invalid_bool(tmp_path):
    p = tmp_path / "client.ini"
    p.write_text("[ui]\nascii = maybe\n")
    with pytest.raises(ConfigError):
        load_client_config(p)


def test_examples_load():
    assert isinstance(load_client_config(ROOT / "config" / "client.example.ini"), ClientConfig)
    assert isinstance(load_host_config(ROOT / "config" / "host.example.ini"), HostConfig)


def test_percent_sign_is_literal(tmp_path):
    p = tmp_path / "client.ini"
    p.write_text("[security]\npin = 12%34\n")
    assert load_client_config(p).pin == "12%34"
