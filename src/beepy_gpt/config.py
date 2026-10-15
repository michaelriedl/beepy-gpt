"""INI config loading and standard directories."""

from __future__ import annotations

import configparser
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "beepy-gpt"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "beepy-gpt"


class ConfigError(ValueError):
    """Invalid configuration value."""


@dataclass
class HostConfig:
    hook_timeout_seconds: int = 600
    agents_poll_seconds: float = 3.0
    state_dir: Path = field(default_factory=state_dir)


@dataclass
class ClientConfig:
    ssh_target: str = ""
    ssh_options: list[str] = field(default_factory=list)
    host_command: str = "bgpt-host"
    host_label: str = "host"
    ui_tier: str = "lite"
    ascii: bool = False
    sysfs_root: Path = Path("/sys/firmware/beepy")
    led_alerts: bool = True
    charge_rise_mv: int = 15
    wifi_interface: str = "wlan0"
    pin: str = ""
    pin_idle_minutes: int = 10
    # Code points the console font can draw; detected at startup, not read from the file.
    glyphs: Optional[frozenset] = None


def _bool(raw: str) -> bool:
    v = raw.lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(raw)


def _read(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None)
    if path.exists():
        try:
            cp.read(path, encoding="utf-8")
        except configparser.Error as e:
            raise ConfigError(f"{path}: {e}") from None
    return cp


def _get(
    cp: configparser.ConfigParser,
    section: str,
    key: str,
    conv: Callable[[str], Any],
    default: Any,
) -> Any:
    raw = cp.get(section, key, fallback="").strip()
    if raw == "":
        return default
    try:
        return conv(raw)
    except ValueError:
        raise ConfigError(f"[{section}] {key}: invalid value {raw!r}") from None


def _path(raw: str) -> Path:
    return Path(raw).expanduser()


def load_host_config(path: Optional[Path] = None) -> HostConfig:
    cp = _read(path or config_dir() / "host.ini")
    d = HostConfig()
    return HostConfig(
        hook_timeout_seconds=_get(cp, "hook", "timeout_seconds", int, d.hook_timeout_seconds),
        agents_poll_seconds=_get(cp, "poll", "agents_seconds", float, d.agents_poll_seconds),
        state_dir=_get(cp, "state", "dir", _path, d.state_dir),
    )


def load_client_config(path: Optional[Path] = None) -> ClientConfig:
    cp = _read(path or config_dir() / "client.ini")
    d = ClientConfig()
    return ClientConfig(
        ssh_target=_get(cp, "host", "ssh_target", str, d.ssh_target),
        ssh_options=_get(cp, "host", "ssh_options", shlex.split, []),
        host_command=_get(cp, "host", "host_command", str, d.host_command),
        host_label=_get(cp, "host", "label", str, d.host_label),
        ui_tier=_get(cp, "ui", "tier", str, d.ui_tier),
        ascii=_get(cp, "ui", "ascii", _bool, d.ascii),
        sysfs_root=_get(cp, "device", "sysfs_root", _path, d.sysfs_root),
        led_alerts=_get(cp, "device", "led_alerts", _bool, d.led_alerts),
        charge_rise_mv=_get(cp, "device", "charge_rise_mv", int, d.charge_rise_mv),
        wifi_interface=_get(cp, "wifi", "interface", str, d.wifi_interface),
        pin=_get(cp, "security", "pin", str, d.pin),
        pin_idle_minutes=_get(cp, "security", "pin_idle_minutes", int, d.pin_idle_minutes),
    )
