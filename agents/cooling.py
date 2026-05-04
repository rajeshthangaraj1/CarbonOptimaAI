from datetime import timedelta

import pandas as pd

from core import config


class CoolingAgent:
    """Thermal-lag pre-cool + setback plan generator.

    Pre-cool: drop the setpoint by `depth_c` for `lookback_hr` hours
    immediately before the peak, then coast (raise the setpoint by
    `depth_c`) through the peak. Net hourly kWh sums to zero in this
    simplified model — the carbon win comes entirely from shifting the
    cooling load to lower-intensity hours (typically 09:00–11:00 when
    UAE solar share is highest).

    Setback: raise the setpoint during the peak with no pre-cool.
    Pure energy reduction at the cost of comfort.

    Both methods return a list of hourly action dicts:
        {"kind": str, "ts_start": Timestamp, "ts_end": Timestamp, "kwh_delta": float}
    where positive `kwh_delta` means *consume more* in that hour.
    """

    def __init__(self):
        self.coef = config.get("cooling.coef_kwh_per_c")

    def precool_plan(self, window_start, window_end, depth_c, lookback_hr):
        delta = self.coef * depth_c
        window_hours = self._inclusive_hours(window_start, window_end)

        actions = []
        for h in range(lookback_hr):
            ts = window_start - timedelta(hours=lookback_hr - h)
            actions.append(self._row("pre_cool", ts, +delta))
        for h in range(window_hours):
            ts = window_start + timedelta(hours=h)
            actions.append(self._row("coast", ts, -delta))
        return actions

    def setback_plan(self, window_start, window_end, depth_c):
        delta = self.coef * depth_c
        window_hours = self._inclusive_hours(window_start, window_end)
        return [
            self._row("setback", window_start + timedelta(hours=h), -delta)
            for h in range(window_hours)
        ]

    @staticmethod
    def _inclusive_hours(start, end):
        return int((end - start).total_seconds() // 3600) + 1

    @staticmethod
    def _row(kind, ts, kwh_delta):
        ts = pd.Timestamp(ts)
        return {
            "kind":      kind,
            "ts_start":  ts,
            "ts_end":    ts + pd.Timedelta(hours=1),
            "kwh_delta": float(kwh_delta),
        }
