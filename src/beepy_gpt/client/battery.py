"""Battery smoothing and a best-guess charging flag (the hardware exposes none)."""

from __future__ import annotations

import math
from collections import deque
from typing import Optional


class BatteryTracker:
    def __init__(
        self,
        tau_s: float = 60.0,
        charge_window_s: float = 180.0,
        charge_rise_mv: int = 15,
        low_percent: int = 15,
    ):
        self.tau_s = tau_s
        self.charge_window_s = charge_window_s
        self.charge_rise_mv = charge_rise_mv
        self.low_percent = low_percent
        self._t: Optional[float] = None
        self._v = 0.0
        self._p = 0.0
        self._hist: deque = deque()

    def add(self, t: float, percent: int, volts: float) -> None:
        if self._t is None:
            self._v, self._p = volts, float(percent)
        else:
            alpha = 1.0 - math.exp(-max(0.0, t - self._t) / self.tau_s)
            self._v += alpha * (volts - self._v)
            self._p += alpha * (percent - self._p)
        self._t = t
        self._hist.append((t, self._v))
        while self._hist and t - self._hist[0][0] > self.charge_window_s:
            self._hist.popleft()

    @property
    def percent(self) -> Optional[int]:
        return None if self._t is None else int(round(self._p))

    @property
    def charging(self) -> bool:
        if len(self._hist) < 2:
            return False
        (t0, v0), (t1, v1) = self._hist[0], self._hist[-1]
        if t1 - t0 < 0.5 * self.charge_window_s:
            return False
        return (v1 - v0) * 1000.0 >= self.charge_rise_mv

    @property
    def low(self) -> bool:
        p = self.percent
        return p is not None and p < self.low_percent
