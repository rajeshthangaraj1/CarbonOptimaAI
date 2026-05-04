import pandas as pd

from core.db import connect


class CarbonAgent:
    """Joins consumption with hourly grid intensity to produce kg CO2 per hour."""

    def emissions(self, start=None, end=None):
        q = (
            "SELECT c.ts, c.kwh, "
            "       g.intensity_kg_per_kwh, g.gas_share, g.solar_share, g.nuclear_share "
            "FROM consumption c JOIN grid_intensity g ON c.ts = g.ts"
        )
        params = []
        if start and end:
            q += " WHERE c.ts BETWEEN ? AND ?"
            params = [start, end]
        q += " ORDER BY c.ts"
        with connect() as conn:
            df = pd.read_sql_query(q, conn, params=params, parse_dates=["ts"])
        df = df.set_index("ts").sort_index()
        df["kg_co2"] = df["kwh"] * df["intensity_kg_per_kwh"]
        return df

    def summary(self, df=None):
        if df is None:
            df = self.emissions()
        return {
            "total_kwh":         float(df["kwh"].sum()),
            "total_kg_co2":      float(df["kg_co2"].sum()),
            "avg_intensity":     float(df["intensity_kg_per_kwh"].mean()),
            "peak_kwh":          float(df["kwh"].max()),
            "peak_kg_co2":       float(df["kg_co2"].max()),
            "peak_kg_co2_ts":    str(df["kg_co2"].idxmax()),
            "rows":              int(len(df)),
        }

    def hot_windows(self, top_n=20, df=None):
        if df is None:
            df = self.emissions()
        return df.nlargest(top_n, "kg_co2")[["kwh", "intensity_kg_per_kwh", "kg_co2"]]
