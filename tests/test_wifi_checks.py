import json

import pytest

from beepy_gpt.client.wifi import WifiError, WifiStatus
from beepy_gpt.client.wifi.checks import Connectivity, check_internet, check_tailscale, run_checks
from beepy_gpt.client.wifi.fake import FakeWifi
from helpers import FakeRun


class Resp:
    def __init__(self, status, location=None):
        self.status = status
        self._location = location

    def getheader(self, name):
        return self._location if name == "Location" else None

    def read(self, n=-1):
        return b""


class Conn:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = resp, exc

    def request(self, *a, **k):
        if self.exc:
            raise self.exc

    def getresponse(self):
        return self.resp

    def close(self):
        pass


def test_internet_ok():
    assert check_internet(lambda: Conn(Resp(204))) == (True, None)


def test_captive_redirect():
    ok, url = check_internet(lambda: Conn(Resp(302, "http://portal.example/login")))
    assert not ok and url == "http://portal.example/login"


def test_captive_200_page():
    ok, url = check_internet(lambda: Conn(Resp(200)))
    assert not ok and url == "http://connectivitycheck.gstatic.com/generate_204"


def test_no_network():
    assert check_internet(lambda: Conn(exc=OSError("unreachable"))) == (False, None)


def test_tailscale():
    run = FakeRun()
    run.on(["tailscale", "status", "--json"], stdout=json.dumps({"BackendState": "Running"}))
    assert check_tailscale(run=run, which=lambda n: "/usr/bin/tailscale") is True
    assert check_tailscale(run=FakeRun(), which=lambda n: "/usr/bin/tailscale") is False
    assert check_tailscale(run=run, which=lambda n: None) is None


def test_run_checks_without_ip_skips_internet():
    called = []
    result = run_checks(WifiStatus(), internet=lambda: called.append(1) or (True, None), tailscale=lambda: None)
    assert result == Connectivity(None, False, None, None) and called == []


def test_run_checks_with_ip():
    result = run_checks(WifiStatus("X", 80, "10.0.0.2"), internet=lambda: (True, None), tailscale=lambda: True)
    assert result == Connectivity("10.0.0.2", True, None, True)


def test_fake_wifi_flow():
    w = FakeWifi()
    assert [n.ssid for n in w.scan()][0] == "HomeNet"
    with pytest.raises(WifiError) as e:
        w.connect("CoffeeShop", "wrongpass")
    assert e.value.code == "auth_failed"
    w.connect("Airport_Free")
    st = w.status()
    assert st.ssid == "Airport_Free" and st.ip
    assert w.checks(st).captive_url == "http://portal.example/login"
    w.forget("HomeNet")
    assert not next(n for n in w.scan() if n.ssid == "HomeNet").saved


def test_fake_wifi_weak_signal_drops_out():
    w = FakeWifi()
    w.connect("Weak Signal", "longenough")
    assert w.status() == WifiStatus()
    assert not any(n.active for n in w.scan())
    assert w.checks(w.status()) == Connectivity(None, False, None, False)


def test_fake_wifi_errors_never_contain_password():
    w = FakeWifi()
    with pytest.raises(WifiError) as e:
        w.connect("CoffeeShop", "wrongpass")
    assert "wrongpass" not in e.value.message
    with pytest.raises(WifiError) as e:
        w.connect("CoffeeShop", None)
    assert "wrongpass" not in e.value.message
