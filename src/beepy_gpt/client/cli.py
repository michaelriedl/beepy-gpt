"""`bgpt` command line entry point: wires transport, device, Wi-Fi and the UI."""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from beepy_gpt import __version__
from beepy_gpt.config import ClientConfig, ConfigError, load_client_config, state_dir


def host_argv(cfg: ClientConfig, fake: bool) -> list[str]:
    if fake:
        return [sys.executable, "-m", "beepy_gpt.host.cli", "serve", "--fake"]
    if not cfg.ssh_target:
        raise ConfigError("set [host] ssh_target in ~/.config/beepy-gpt/client.ini (see config/client.example.ini)")
    from beepy_gpt.client.transport import ssh_argv

    return ssh_argv(cfg.ssh_target, cfg.ssh_options, cfg.host_command)


def _poll(stop: threading.Event, every: float, fn: Any) -> None:
    def loop() -> None:
        while not stop.is_set():
            try:
                fn()
            except Exception:
                logging.getLogger(__name__).exception("poller failed")
            stop.wait(every)

    threading.Thread(target=loop, daemon=True).start()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="bgpt", description="Beepy client for Claude Code sessions")
    p.add_argument("--version", action="version", version=f"bgpt {__version__}")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--emulate", action="store_true", help="desktop emulator (50x30 frame, fake device)")
    p.add_argument("--host", choices=("ssh", "fake"), default=None, help="default: fake with --emulate, else ssh")
    p.add_argument("command", nargs="?", choices=("doctor",))
    args = p.parse_args(argv)

    try:
        cfg = load_client_config(args.config)
    except ConfigError as e:
        print(f"bgpt: {e}", file=sys.stderr)
        return 2
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(sd / "client.log"), level=logging.INFO)

    from beepy_gpt.client.device import open_device
    from beepy_gpt.client.wifi import detect_backend

    if args.command == "doctor":
        from beepy_gpt.client.doctor import run_client_doctor

        return run_client_doctor(cfg, print, device=open_device(cfg.sysfs_root),
                                 wifi=detect_backend(cfg.wifi_interface))

    from beepy_gpt.client.app import App
    from beepy_gpt.client.transport import Transport
    from beepy_gpt.client.ui_curses import run

    frame = None
    wifi: Any = None
    checks = None
    if args.emulate:
        from beepy_gpt.client.emulator import Emulator
        from beepy_gpt.client.wifi.fake import FakeWifi

        frame = Emulator()
        cfg.sysfs_root = frame.sysfs_root
        wifi = FakeWifi()
        checks = wifi.checks
    else:
        wifi = detect_backend(cfg.wifi_interface)
    fake_host = (args.host or ("fake" if args.emulate else "ssh")) == "fake"
    try:
        argv_host = host_argv(cfg, fake_host)
    except ConfigError as e:
        print(f"bgpt: {e}", file=sys.stderr)
        return 2

    events: "queue.Queue[dict]" = queue.Queue()
    device = open_device(cfg.sysfs_root)
    transport = Transport(argv_host, events.put, lambda s: events.put({"type": "connection", "status": s}),
                          stderr_path=sd / "host-stderr.log")
    app = App(cfg, transport.request, events.put, device, wifi=wifi, checks=checks)
    stop = threading.Event()
    if device.available:
        def sample() -> None:
            reading = device.read_battery()
            if reading:
                events.put({"type": "battery_sample", "percent": reading[0], "volts": reading[1]})

        _poll(stop, 10, sample)
    if wifi is not None:
        def wifi_status() -> None:
            events.put({"type": "wifi_status", "status": wifi.status()})

        _poll(stop, 15, wifi_status)
    transport.start()
    try:
        run(app, events, frame=frame)
    finally:
        stop.set()
        transport.stop()
        device.set_led_alert(False)
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())
