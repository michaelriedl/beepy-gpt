import os
import logging

from beepy_gpt.client.device import Device, NullDevice, open_device


def make_sysfs(tmp_path):
    root = tmp_path / "beepy"
    root.mkdir()
    for name, value in {"battery_percent": "63\n", "battery_volts": "3.812\n", "led": "0",
                        "led_red": "0", "led_green": "0", "led_blue": "0"}.items():
        (root / name).write_text(value)
    return root


def test_reads_battery(tmp_path):
    d = Device(make_sysfs(tmp_path))
    assert d.available and d.read_battery() == (63, 3.812)


def test_led_alert_on_off(tmp_path):
    root = make_sysfs(tmp_path)
    d = Device(root)
    d.set_led_alert(True)
    assert (root / "led").read_text() == "3" and (root / "led_blue").read_text() == "255"
    d.set_led_alert(False)
    assert (root / "led").read_text() == "0"


def test_unreadable_values(tmp_path):
    root = make_sysfs(tmp_path)
    (root / "battery_volts").write_text("garbage")
    assert Device(root).read_battery() is None


def test_led_write_error_is_logged_once_not_raised(tmp_path, caplog):
    root = make_sysfs(tmp_path)
    (root / "led").unlink()
    (root / "led").mkdir()  # writing to a directory fails
    d = Device(root)
    d.set_led_alert(True)
    d.set_led_alert(True)
    assert (root / "led_blue").read_text() == "255"  # the other writes still happened
    assert len([r for r in caplog.records if "cannot write" in r.getMessage()]) == 1


def test_open_device_missing_root(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="beepy_gpt.client.device")
    d = open_device(tmp_path / "missing")
    assert isinstance(d, NullDevice) and not d.available and d.read_battery() is None
    d.set_led_alert(True)
    assert any("no Beepy firmware" in r.getMessage() for r in caplog.records)


def test_led_writable(tmp_path):
    d = Device(make_sysfs(tmp_path))
    (d.root / "led").write_text("0")
    assert d.led_writable()
    (d.root / "led").chmod(0o444)
    assert d.led_writable() == (os.geteuid() == 0)  # root ignores file modes
