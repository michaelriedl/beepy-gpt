import pytest

from beepy_gpt.client.wifi import Network, WifiError, WifiStatus
from beepy_gpt.client.wifi.wpa import WpaBackend, dbm_to_percent
from helpers import FakeRun

W = ["wpa_cli", "-i", "wlan0"]
SCAN_RESULTS = (
    "bssid / frequency / signal level / flags / ssid\n"
    "aa:aa:aa:aa:aa:01\t2437\t-45\t[WPA2-PSK-CCMP][ESS]\tHomeNet\n"
    "aa:aa:aa:aa:aa:02\t2412\t-80\t[ESS]\tAirport_Free\n"
    "aa:aa:aa:aa:aa:03\t2412\t-60\t[WPA2-PSK-CCMP][ESS]\tHomeNet\n"
    "aa:aa:aa:aa:aa:04\t2412\t-70\t[WPA2-PSK-CCMP][ESS]\t\n"
)
LIST_NETWORKS = "network id / ssid / bssid / flags\n0\tHomeNet\tany\t[CURRENT]\n"


def backend(run):
    return WpaBackend(run=run, sleep=lambda s: None, connect_timeout=3)


def test_dbm_to_percent():
    assert [dbm_to_percent(d) for d in (-30, -45, -100, -120)] == [100, 100, 0, 0]
    assert dbm_to_percent(-70) == 60


def test_scan():
    run = FakeRun()
    run.on(W + ["scan"], stdout="OK\n")
    run.on(W + ["scan_results"], stdout=SCAN_RESULTS)
    run.on(W + ["list_networks"], stdout=LIST_NETWORKS)
    run.on(W + ["status"], stdout="wpa_state=COMPLETED\nssid=HomeNet\n")
    assert backend(run).scan() == [
        Network("HomeNet", 100, True, saved=True, active=True),
        Network("Airport_Free", 40, False),
    ]


def test_status():
    run = FakeRun()
    run.on(W + ["status"], stdout="wpa_state=COMPLETED\nssid=HomeNet\nip_address=192.168.4.20\n")
    run.on(W + ["signal_poll"], stdout="RSSI=-52\nLINKSPEED=65\n")
    assert backend(run).status() == WifiStatus("HomeNet", 96, "192.168.4.20")


def test_status_disconnected():
    run = FakeRun()
    run.on(W + ["status"], stdout="wpa_state=DISCONNECTED\n")
    assert backend(run).status() == WifiStatus()


def test_connect_new_secured_network():
    run = FakeRun()
    run.on(W + ["list_networks"], stdout="network id / ssid / bssid / flags\n")
    run.on(W + ["add_network"], stdout="1\n")
    run.on(W + ["set_network"], stdout="OK\n")
    run.on(W + ["enable_network"], stdout="OK\n")
    run.on(W + ["select_network"], stdout="OK\n")
    run.on(W + ["save_config"], stdout="OK\n")
    run.on(W + ["status"], stdout="wpa_state=COMPLETED\nssid=Cafe\n")
    backend(run).connect("Cafe", "hunter2222")
    assert W + ["set_network", "1", "ssid", "43616665"] in run.calls
    assert W + ["set_network", "1", "psk", '"hunter2222"'] in run.calls
    assert W + ["select_network", "1"] in run.calls


def test_connect_open_hidden_network():
    run = FakeRun()
    run.on(W + ["list_networks"], stdout="network id / ssid / bssid / flags\n")
    run.on(W + ["add_network"], stdout="2\n")
    run.on(W + ["set_network"], stdout="OK\n")
    run.on(W + ["enable_network"], stdout="OK\n")
    run.on(W + ["select_network"], stdout="OK\n")
    run.on(W + ["save_config"], stdout="OK\n")
    run.on(W + ["status"], stdout="wpa_state=COMPLETED\nssid=Lab\n")
    backend(run).connect("Lab", None, hidden=True)
    assert W + ["set_network", "2", "key_mgmt", "NONE"] in run.calls
    assert W + ["set_network", "2", "scan_ssid", "1"] in run.calls


def test_connect_saved_network_just_selects():
    run = FakeRun()
    run.on(W + ["list_networks"], stdout=LIST_NETWORKS)
    run.on(W + ["select_network"], stdout="OK\n")
    run.on(W + ["status"], stdout="wpa_state=COMPLETED\nssid=HomeNet\n")
    backend(run).connect("HomeNet")
    assert not any(c[3:4] == ["add_network"] for c in run.calls)


def test_connect_timeout_removes_new_network_and_hides_password():
    run = FakeRun()
    run.on(W + ["list_networks"], stdout="network id / ssid / bssid / flags\n")
    run.on(W + ["add_network"], stdout="3\n")
    run.on(W + ["set_network"], stdout="OK\n")
    run.on(W + ["enable_network"], stdout="OK\n")
    run.on(W + ["select_network"], stdout="OK\n")
    run.on(W + ["remove_network"], stdout="OK\n")
    run.on(W + ["status"], stdout="wpa_state=4WAY_HANDSHAKE\n")
    with pytest.raises(WifiError) as e:
        backend(run).connect("Cafe", "wrongpass1")
    assert e.value.code == "auth_failed" and "wrongpass1" not in str(e.value)
    assert W + ["remove_network", "3"] in run.calls


def test_short_password_rejected_before_running_anything():
    run = FakeRun()
    with pytest.raises(WifiError) as e:
        backend(run).connect("Cafe", "short")
    assert e.value.code == "auth_failed" and run.calls == []


def test_password_never_appears_in_error_even_if_wpa_cli_echoes_it():
    run = FakeRun()
    run.on(W + ["list_networks"], stdout="network id / ssid / bssid / flags\n")
    run.on(W + ["add_network"], stdout="4\n")
    run.on(W + ["set_network"], returncode=1, stdout="", stderr="bad psk hunter2222 near psk")
    run.on(W + ["remove_network"], stdout="OK\n")
    with pytest.raises(WifiError) as e:
        backend(run).connect("Cafe", "hunter2222")
    assert e.value.code == "backend"
    assert "hunter2222" not in str(e.value) and "hunter2222" not in e.value.message
    assert e.value.__context__ is None
    assert W + ["remove_network", "4"] in run.calls


def test_permission_error():
    run = FakeRun()
    run.on(W + ["scan"], returncode=255,
           stdout="Failed to connect to non-global ctrl_ifname: wlan0  error: Permission denied\n")
    with pytest.raises(WifiError) as e:
        backend(run).scan()
    assert e.value.code == "permission"


def test_forget():
    run = FakeRun()
    run.on(W + ["list_networks"], stdout=LIST_NETWORKS)
    run.on(W + ["remove_network"], stdout="OK\n")
    run.on(W + ["save_config"], stdout="OK\n")
    backend(run).forget("HomeNet")
    assert W + ["remove_network", "0"] in run.calls
