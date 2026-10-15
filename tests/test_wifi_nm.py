import pytest

from beepy_gpt.client.wifi import Network, WifiError, WifiStatus, detect_backend, signal_bars
from beepy_gpt.client.wifi.nm import NmBackend, split_terse
from helpers import FakeRun

LIST = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", "wlan0"]


def test_split_terse():
    assert split_terse(r"*:Cafe\:Free:40:WPA2") == ["*", "Cafe:Free", "40", "WPA2"]
    assert split_terse(r" :back\\slash:5:") == [" ", "back\\slash", "5", ""]


def test_signal_bars():
    assert [signal_bars(s) for s in (90, 50, 10, None)] == ["▂▄▆", "▂▄_", "▂__", "___"]
    assert signal_bars(90, ascii=True) == "###"


def test_scan_parses_dedupes_and_sorts():
    run = FakeRun()
    run.on(LIST + ["--rescan", "yes"], stdout=(
        " :Cafe\\:Free:40:\n"
        "*:HomeNet:82:WPA2\n"
        " :HomeNet:30:WPA2\n"
        " ::70:WPA2\n"
        " :Strong:90:WPA1 WPA2\n"
    ))
    run.on(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
           stdout="HomeNet:802-11-wireless\nWired:802-3-ethernet\n")
    nets = NmBackend(run=run).scan()
    assert nets == [
        Network("HomeNet", 82, True, saved=True, active=True),
        Network("Strong", 90, True),
        Network("Cafe:Free", 40, False),
    ]


def test_status():
    run = FakeRun()
    run.on(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list"], stdout="*:HomeNet:82\n :Other:20\n")
    run.on(["nmcli", "-t", "-g", "IP4.ADDRESS", "device", "show", "wlan0"], stdout="192.168.4.20/24\n")
    assert NmBackend(run=run).status() == WifiStatus("HomeNet", 82, "192.168.4.20")


def test_connect_args_and_password_not_in_error():
    run = FakeRun()
    run.on(["nmcli", "device", "wifi", "connect"], returncode=4,
           stderr="Error: Connection activation failed: Secrets were required, but not provided.")
    with pytest.raises(WifiError) as e:
        NmBackend(run=run).connect("Cafe", "hunter22", hidden=True)
    assert e.value.code == "auth_failed" and "hunter22" not in str(e.value)
    assert run.calls[-1] == ["nmcli", "device", "wifi", "connect", "Cafe", "ifname", "wlan0",
                             "password", "hunter22", "hidden", "yes"]


def test_password_is_redacted_from_error_message():
    run = FakeRun()
    run.on(["nmcli", "device", "wifi", "connect"], returncode=2,
           stderr="Error: invalid extra argument 'hunter22'.")
    with pytest.raises(WifiError) as e:
        NmBackend(run=run).connect("Cafe", "hunter22")
    assert "hunter22" not in e.value.message and "***" in e.value.message


def test_nmcli_runs_with_c_locale():
    run = FakeRun()
    run.on(["nmcli", "connection", "delete"], stdout="deleted")
    NmBackend(run=run).forget("HomeNet")
    assert run.envs[-1]["LC_ALL"] == "C"


@pytest.mark.parametrize("stderr,code", [
    ("Error: Not authorized to control networking.", "permission"),
    ("Error: No network with SSID 'X' found.", "not_found"),
    ("Error: something else", "backend"),
])
def test_error_mapping(stderr, code):
    run = FakeRun()
    run.on(["nmcli", "device", "wifi", "connect"], returncode=1, stderr=stderr)
    with pytest.raises(WifiError) as e:
        NmBackend(run=run).connect("X")
    assert e.value.code == code


def test_forget():
    run = FakeRun()
    run.on(["nmcli", "connection", "delete"], stdout="deleted")
    NmBackend(run=run).forget("HomeNet")
    assert run.calls[-1] == ["nmcli", "connection", "delete", "id", "HomeNet"]


def test_detect_prefers_running_networkmanager():
    run = FakeRun()
    run.on(["/usr/bin/nmcli", "-t", "-f", "RUNNING", "general"], stdout="running\n")
    b = detect_backend(run=run, which=lambda name: f"/usr/bin/{name}")
    assert b.name == "networkmanager"
    assert b._tool == "/usr/bin/nmcli"


def test_detect_finds_wpa_cli_outside_path():
    # Raspberry Pi OS: wpa_cli is in /usr/sbin, which a normal user's PATH leaves out.
    run = FakeRun()
    run.on(["/usr/sbin/wpa_cli", "-i", "wlan0", "ping"], stdout="PONG\n")
    b = detect_backend(run=run, which=lambda name: None, is_file=lambda path: path == "/usr/sbin/wpa_cli")
    assert b.name == "wpa_supplicant"
    assert b._tool == "/usr/sbin/wpa_cli"


def test_detect_none():
    assert detect_backend(run=FakeRun(), which=lambda name: None, is_file=lambda path: False) is None
