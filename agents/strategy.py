from core import config
from core.db import connect

from .cooling import CoolingAgent

TS_FMT = "%Y-%m-%d %H:%M:%S"


class StrategyAgent:
    """Generates and scores 4 candidate strategies per anomaly window.

    Each candidate is a coherent plan (not a single action). The returned
    dicts carry the hourly action list plus the totals OrchestrationAgent
    needs: `kg_co2_saved`, `kwh_net`, `comfort_cost`. CO2 savings are
    computed against the *actual* hourly intensity series in the DB, not
    a flat factor.
    """

    def __init__(self):
        self.cooling = CoolingAgent()
        self.band = config.get("building.comfort_band_c")

    def candidates(self, window_start, window_end):
        b = self.band
        plans = [
            ("conservative_precool", self.cooling.precool_plan(window_start, window_end, depth_c=b * 0.5, lookback_hr=2), 0.5),
            ("standard_precool",     self.cooling.precool_plan(window_start, window_end, depth_c=b,        lookback_hr=3), 1.0),
            ("aggressive_precool",   self.cooling.precool_plan(window_start, window_end, depth_c=b * 1.3,  lookback_hr=4), 2.0),
            ("setback_only",         self.cooling.setback_plan(window_start, window_end, depth_c=b * 0.7),                  1.5),
        ]
        scored = [
            self._score({
                "name":         name,
                "window_start": window_start,
                "window_end":   window_end,
                "actions":      actions,
                "comfort_cost": comfort_cost,
            })
            for name, actions, comfort_cost in plans
        ]
        return scored

    def _score(self, candidate):
        ts_keys = sorted({a["ts_start"].strftime(TS_FMT) for a in candidate["actions"]})
        if not ts_keys:
            candidate["kg_co2_saved"] = 0.0
            candidate["kwh_net"] = 0.0
            return candidate

        placeholders = ",".join("?" * len(ts_keys))
        with connect() as conn:
            rows = conn.execute(
                f"SELECT ts, intensity_kg_per_kwh FROM grid_intensity WHERE ts IN ({placeholders})",
                tuple(ts_keys),
            ).fetchall()
        intensity = {r["ts"]: r["intensity_kg_per_kwh"] for r in rows}

        kg_co2_saved = 0.0
        kwh_net = 0.0
        for a in candidate["actions"]:
            i = intensity.get(a["ts_start"].strftime(TS_FMT))
            if i is None:
                continue
            kg_co2_saved += -a["kwh_delta"] * i
            kwh_net      += a["kwh_delta"]

        candidate["kg_co2_saved"] = float(kg_co2_saved)
        candidate["kwh_net"]      = float(kwh_net)
        return candidate
