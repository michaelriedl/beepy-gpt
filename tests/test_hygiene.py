import configparser
from pathlib import Path

import beepy_gpt

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_TARGETS = {"user@workstation"}


def _ini(name: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    assert cp.read(ROOT / "config" / name), f"missing config/{name}"
    return cp


def test_version_is_semver():
    parts = beepy_gpt.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_client_example_uses_only_placeholders():
    cp = _ini("client.example.ini")
    assert cp["host"]["ssh_target"] in PLACEHOLDER_TARGETS
    assert cp["host"]["ssh_options"] == ""
    assert cp["security"]["pin"] == ""


def test_host_example_has_no_paths():
    cp = _ini("host.example.ini")
    assert cp["state"]["dir"] == ""
