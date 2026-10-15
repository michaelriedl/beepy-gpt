import curses

import pytest

from beepy_gpt.client import cli, ui_curses


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, sub in (("XDG_CONFIG_HOME", "cfg"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
        monkeypatch.setenv(k, str(tmp_path / sub))
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


class FakeTransport:
    instances = []

    def __init__(self, *a, **k):
        self.started = self.stopped = False
        self.request = lambda *a, **k: None
        FakeTransport.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeDevice:
    available = False

    def __init__(self):
        self.led = []

    def set_led_alert(self, on):
        self.led.append(on)

    def read_battery(self):
        return None


def patch(monkeypatch, run, device):
    from beepy_gpt.client import device as devmod, transport, wifi

    FakeTransport.instances = []
    monkeypatch.setattr(transport, "Transport", FakeTransport)
    monkeypatch.setattr(ui_curses, "run", run)
    monkeypatch.setattr(devmod, "open_device", lambda root: device)
    monkeypatch.setattr(wifi, "detect_backend", lambda iface: None)


def test_missing_ssh_target_returns_2(env, capsys):
    assert cli.main([]) == 2
    assert "ssh_target" in capsys.readouterr().err


def test_bad_config_returns_2(env, capsys):
    bad = env / "bad.ini"
    bad.write_text("[host\nnonsense")
    assert cli.main(["--config", str(bad)]) == 2
    assert "bgpt:" in capsys.readouterr().err


def test_doctor_dispatches(env, monkeypatch, capsys):
    from beepy_gpt.client import doctor

    seen = {}
    monkeypatch.setattr(doctor, "run_client_doctor", lambda cfg, out, **kw: seen.update(cfg=cfg, kw=kw) or 7)
    from beepy_gpt.client import device as devmod, wifi

    monkeypatch.setattr(devmod, "open_device", lambda root: FakeDevice())
    monkeypatch.setattr(wifi, "detect_backend", lambda iface: None)
    assert cli.main(["doctor"]) == 7
    assert "device" in seen["kw"]


def test_cleanup_runs_when_ui_raises(env, monkeypatch):
    dev = FakeDevice()

    def boom(app, events, frame=None):
        raise RuntimeError("ui died")

    patch(monkeypatch, boom, dev)
    cfgf = env / "c.ini"
    cfgf.write_text("[host]\nssh_target = user@workstation\n")
    with pytest.raises(RuntimeError):
        cli.main(["--config", str(cfgf)])
    t = FakeTransport.instances[0]
    assert t.started and t.stopped and dev.led == [False]


def test_ctrl_c_returns_130_after_cleanup(env, monkeypatch):
    dev = FakeDevice()

    def interrupt(app, events, frame=None):
        raise KeyboardInterrupt

    patch(monkeypatch, interrupt, dev)
    cfgf = env / "c.ini"
    cfgf.write_text("[host]\nssh_target = user@workstation\n")
    assert cli.main(["--config", str(cfgf)]) == 130
    assert FakeTransport.instances[0].stopped and dev.led == [False]


def test_cleanup_runs_when_transport_start_fails(env, monkeypatch):
    dev = FakeDevice()
    patch(monkeypatch, lambda *a, **k: None, dev)

    def bad_start(self):
        raise OSError("no ssh")

    monkeypatch.setattr(FakeTransport, "start", bad_start)
    cfgf = env / "c.ini"
    cfgf.write_text("[host]\nssh_target = user@workstation\n")
    with pytest.raises(OSError):
        cli.main(["--config", str(cfgf)])
    assert FakeTransport.instances[0].stopped and dev.led == [False]


# --- ui_curses.run loop with a scripted fake screen ---------------------------

class Screen:
    def __init__(self, script):
        self.script, self.drawn = list(script), 0

    def keypad(self, flag): pass
    def timeout(self, ms): pass
    def erase(self): pass
    def refresh(self): pass

    def addstr(self, y, x, text, attr=0):
        self.drawn += 1

    def get_wch(self):
        if not self.script:
            raise curses.error("no input")
        return self.script.pop(0)


class FakeApp:
    def __init__(self):
        self.running, self.external, self.keys, self.events = True, None, [], []
        from beepy_gpt.client.render.grid import Grid

        self.grid = Grid(cols=4, rows=1)

    def on_event(self, ev): self.events.append(ev)
    def render(self, now): return self.grid

    def on_key(self, key):
        self.keys.append(key)
        if key == "q":
            self.running = False


def run_loop(monkeypatch, app, script, events=None):
    import queue

    scr = Screen(script)
    monkeypatch.setattr(curses, "wrapper", lambda fn: fn(scr))
    monkeypatch.setattr(curses, "curs_set", lambda n: None)
    ui_curses.run(app, events or queue.Queue())
    return scr


def test_run_filters_refused_keys_and_quits(monkeypatch):
    app = FakeApp()
    scr = run_loop(monkeypatch, app, ["\t", curses.KEY_F5, "\x03", "x", "q", "z"])
    assert app.keys == ["x", "q"]  # TAB / F5 / Ctrl-C never reach the app
    assert scr.script == ["z"]  # loop stopped right after the quit key
    assert scr.drawn > 0


def test_run_delivers_queued_events(monkeypatch):
    import queue

    q = queue.Queue()
    q.put({"type": "notice", "text": "hi"})
    app = FakeApp()
    run_loop(monkeypatch, app, ["q"], events=q)
    assert app.events == [{"type": "notice", "text": "hi"}]
