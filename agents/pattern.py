import pandas as pd
from sklearn.ensemble import IsolationForest

from core import config
from core.db import connect

from .carbon import CarbonAgent
from .energy import EnergyAgent


class PatternAgent:
    """Isolation Forest over (consumption, weather, intensity, emissions).

    Surfaces unusual hours and flags them as either an emission peak (when
    co2 sits in the top 5%) or a generic consumption spike.
    """

    FEATURES = ["kwh", "temp_c", "cooling_demand_proxy",
                "intensity_kg_per_kwh", "kg_co2"]

    def __init__(self, contamination=None):
        self.contamination = contamination or config.get("pattern.contamination")
        self.model = IsolationForest(
            contamination=self.contamination, random_state=42, n_estimators=200,
        )

    def _frame(self):
        e = EnergyAgent().load()
        c = CarbonAgent().emissions()[["intensity_kg_per_kwh", "kg_co2"]]
        return e.join(c, how="inner")

    def fit_score(self):
        df = self._frame()
        X = df[self.FEATURES]
        self.model.fit(X)
        df["anomaly_score"] = -self.model.score_samples(X)
        df["is_anomaly"]    = (self.model.predict(X) == -1)
        return df

    def persist(self, df=None):
        if df is None:
            df = self.fit_score()
        threshold = df["kg_co2"].quantile(0.95)
        anom = df[df["is_anomaly"]]
        with connect() as conn:
            conn.execute("DELETE FROM anomalies")
            conn.executemany(
                "INSERT INTO anomalies (ts, score, kind) VALUES (?, ?, ?)",
                [
                    (
                        ts.strftime("%Y-%m-%d %H:%M:%S"),
                        float(row["anomaly_score"]),
                        "emission_peak" if row["kg_co2"] >= threshold else "consumption_spike",
                    )
                    for ts, row in anom.iterrows()
                ],
            )
        return len(anom)

    def windows(self, top_n=None, kind="emission_peak"):
        """Group contiguous anomaly hours into windows.

        Returns a list of dicts with start, end, hours, score (sum of
        per-hour anomaly scores). Pass top_n to keep only the highest-score
        windows; pass kind=None to include all anomalies.
        """
        q = "SELECT ts, score, kind FROM anomalies"
        params = ()
        if kind is not None:
            q += " WHERE kind = ?"
            params = (kind,)
        q += " ORDER BY ts"
        with connect() as conn:
            rows = conn.execute(q, params).fetchall()
        if not rows:
            return []

        windows = []
        bucket = [rows[0]]
        for prev, row in zip(rows, rows[1:]):
            gap = pd.Timestamp(row["ts"]) - pd.Timestamp(prev["ts"])
            if gap == pd.Timedelta(hours=1):
                bucket.append(row)
            else:
                windows.append(bucket)
                bucket = [row]
        windows.append(bucket)

        out = [
            {
                "start": pd.Timestamp(b[0]["ts"]),
                "end":   pd.Timestamp(b[-1]["ts"]),
                "hours": len(b),
                "score": float(sum(r["score"] for r in b)),
                "kind":  b[0]["kind"],
            }
            for b in windows
        ]
        out.sort(key=lambda w: w["score"], reverse=True)
        if top_n:
            out = out[:top_n]
        return out
