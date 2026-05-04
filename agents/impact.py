from datetime import datetime, timezone

import numpy as np

from core import config
from core.db import connect

TS_FMT = "%Y-%m-%d %H:%M:%S"


class ImpactAgent:
    """Counterfactual baseline (do-nothing) vs. optimized scenario, with
    bootstrap CI on the kg CO2 saved.

    The CI captures two real-world uncertainties:
      - action execution noise (we asked for kwh_delta = X but realized X * (1 + ε))
      - intensity forecast noise (the carbon intensity at execution time differs
        from the modeled value)

    Outputs are persisted to `scenarios` (one row per chosen strategy) and
    `actions` (one row per hourly delta).
    """

    def __init__(self, seed=42):
        self.n_boot          = config.get("impact.bootstrap_n")
        self.delta_noise     = config.get("impact.delta_noise")
        self.intensity_noise = config.get("impact.intensity_noise")
        self.rng             = np.random.default_rng(seed)

    def evaluate(self, candidate):
        """Compute baseline/optimized kWh + kg CO2 + CI for a single chosen
        candidate. Does not write to the DB."""
        ts_keys = sorted({a["ts_start"].strftime(TS_FMT) for a in candidate["actions"]})
        if not ts_keys:
            return None

        placeholders = ",".join("?" * len(ts_keys))
        with connect() as conn:
            rows = conn.execute(
                f"SELECT c.ts, c.kwh, g.intensity_kg_per_kwh "
                f"FROM consumption c JOIN grid_intensity g ON c.ts = g.ts "
                f"WHERE c.ts IN ({placeholders})",
                tuple(ts_keys),
            ).fetchall()
        kwh = {r["ts"]: float(r["kwh"]) for r in rows}
        ity = {r["ts"]: float(r["intensity_kg_per_kwh"]) for r in rows}

        delta = {}
        for a in candidate["actions"]:
            key = a["ts_start"].strftime(TS_FMT)
            delta[key] = delta.get(key, 0.0) + float(a["kwh_delta"])

        ts_in = [t for t in ts_keys if t in kwh]
        if not ts_in:
            return None

        baseline_kwh    = sum(kwh[t] for t in ts_in)
        optimized_kwh   = sum(kwh[t] + delta.get(t, 0.0) for t in ts_in)
        baseline_co2    = sum(kwh[t] * ity[t] for t in ts_in)
        optimized_co2   = sum((kwh[t] + delta.get(t, 0.0)) * ity[t] for t in ts_in)
        kg_saved        = baseline_co2 - optimized_co2

        savings = np.empty(self.n_boot)
        kwh_arr   = np.array([kwh[t] for t in ts_in])
        ity_arr   = np.array([ity[t] for t in ts_in])
        delta_arr = np.array([delta.get(t, 0.0) for t in ts_in])

        for b in range(self.n_boot):
            d_jitter = self.rng.normal(1.0, self.delta_noise, len(ts_in))
            i_jitter = self.rng.normal(1.0, self.intensity_noise, len(ts_in))
            realized_intensity = ity_arr * i_jitter
            realized_delta     = delta_arr * d_jitter
            sample_baseline  = (kwh_arr * realized_intensity).sum()
            sample_optimized = ((kwh_arr + realized_delta) * realized_intensity).sum()
            savings[b] = sample_baseline - sample_optimized

        ci_low, ci_high = np.percentile(savings, [2.5, 97.5])
        return {
            "candidate":        candidate,
            "ts_in":            ts_in,
            "baseline_kwh":     float(baseline_kwh),
            "optimized_kwh":    float(optimized_kwh),
            "baseline_kg_co2":  float(baseline_co2),
            "optimized_kg_co2": float(optimized_co2),
            "kg_co2_saved":     float(kg_saved),
            "ci_low":           float(ci_low),
            "ci_high":          float(ci_high),
        }

    def persist(self, evaluation, clear=False):
        """Write one scenario row + N action rows. Returns scenario_id."""
        cand = evaluation["candidate"]
        ws = cand["window_start"]
        we = cand["window_end"]
        created = datetime.now(timezone.utc).strftime(TS_FMT)

        with connect() as conn:
            if clear:
                conn.execute("DELETE FROM narrations")
                conn.execute("DELETE FROM actions")
                conn.execute("DELETE FROM scenarios")
            cur = conn.execute(
                "INSERT INTO scenarios (created_ts, window_start, window_end, "
                "baseline_kwh, optimized_kwh, baseline_kg_co2, optimized_kg_co2, "
                "kg_co2_saved, ci_low, ci_high) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    created,
                    ws.strftime(TS_FMT),
                    we.strftime(TS_FMT),
                    evaluation["baseline_kwh"],
                    evaluation["optimized_kwh"],
                    evaluation["baseline_kg_co2"],
                    evaluation["optimized_kg_co2"],
                    evaluation["kg_co2_saved"],
                    evaluation["ci_low"],
                    evaluation["ci_high"],
                ),
            )
            scenario_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO actions (scenario_id, kind, ts_start, ts_end, kwh_delta, chosen) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                [
                    (
                        scenario_id,
                        a["kind"],
                        a["ts_start"].strftime(TS_FMT),
                        a["ts_end"].strftime(TS_FMT),
                        float(a["kwh_delta"]),
                    )
                    for a in cand["actions"]
                ],
            )
        return scenario_id
