from datetime import datetime

from beepy_gpt.client.device import Device
from beepy_gpt.client.emulator import Emulator


def test_fake_sysfs_feeds_real_device_reader(clock):
    emu = Emulator(clock=clock)
    d = Device(emu.sysfs_root)
    assert d.available and d.read_battery() == (67, 3.9)


def test_controls():
    emu = Emulator()
    assert emu.handle_key("F6") and abs(emu.volts - 3.95) < 1e-9
    assert emu.handle_key("F5") and abs(emu.volts - 3.90) < 1e-9
    assert emu.handle_key("F7") and emu.charging
    assert not emu.handle_key("y")


def test_tick_drifts_battery(clock):
    emu = Emulator(clock=clock)
    emu.handle_key("F7")
    clock.sleep(30)
    assert emu.tick(datetime.now())
    assert abs(emu.volts - 3.906) < 1e-9
    assert (emu.sysfs_root / "battery_volts").read_text() == "3.906"


def test_led_state_reflects_device_writes():
    emu = Emulator()
    Device(emu.sysfs_root).set_led_alert(True)
    assert emu.led_state() == "flash-until-key blue"
    Device(emu.sysfs_root).set_led_alert(False)
    assert emu.led_state() == "off"


def test_refused_key_shown_in_panel():
    emu = Emulator()
    emu.refuse("TAB")
    # The panel is only 25 columns wide, so the key and the reason are on separate lines.
    text = "\n".join(emu.panel_lines())
    assert "refused: TAB" in text and "(not on Beepy)" in text
