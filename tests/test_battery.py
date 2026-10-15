from beepy_gpt.client.battery import BatteryTracker


def feed(tracker, samples, step=10.0, t0=0.0):
    t = t0
    for percent, volts in samples:
        tracker.add(t, percent, volts)
        t += step
    return t


def test_empty_tracker():
    b = BatteryTracker()
    assert b.percent is None and not b.charging and not b.low


def test_constant_voltage_not_charging():
    b = BatteryTracker()
    feed(b, [(60, 3.70)] * 30)
    assert b.percent == 60 and not b.charging


def test_noisy_percent_is_stable():
    b = BatteryTracker()
    feed(b, [(21, 3.415), (22, 3.42), (21, 3.418)] * 20)
    assert b.percent in (21, 22)
    seen = set()
    t = 600.0
    for p, v in [(21, 3.415), (22, 3.42), (21, 3.418)] * 5:
        b.add(t, p, v)
        t += 10
        seen.add(b.percent)
    assert len(seen) == 1


def test_noisy_voltage_not_charging():
    b = BatteryTracker()
    feed(b, [(50, 3.70), (50, 3.71)] * 30)
    assert not b.charging


def test_rising_voltage_is_charging():
    b = BatteryTracker()
    feed(b, [(30, 3.40 + 0.002 * i) for i in range(40)])  # +12 mV/min
    assert b.charging


def test_short_history_never_charging():
    b = BatteryTracker()
    feed(b, [(30, 3.40), (30, 3.60)])
    assert not b.charging


def test_low():
    b = BatteryTracker()
    feed(b, [(9, 3.30)] * 3)
    assert b.low
