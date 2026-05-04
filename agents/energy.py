import pandas as pd

from core import config
from core.db import connect


class EnergyAgent:
    """Loads consumption + weather, joins them, and builds features."""

    def load(self, start=None, end=None):
        q = (
            "SELECT c.ts, c.kwh, w.temp_c, w.humidity, w.irradiance_wm2 "
            "FROM consumption c JOIN weather w ON c.ts = w.ts"
        )
        params = []
        if start and end:
            q += " WHERE c.ts BETWEEN ? AND ?"
            params = [start, end]
        q += " ORDER BY c.ts"
        with connect() as conn:
            df = pd.read_sql_query(q, conn, params=params, parse_dates=["ts"])
        return self._features(df)

    def _features(self, df):
        setpoint = config.get("building.cooling_setpoint_c")
        df = df.set_index("ts").sort_index()
        df["hour"]                  = df.index.hour
        df["dow"]                   = df.index.dayofweek
        df["is_weekend"]            = (df["dow"] >= 5).astype(int)
        df["month"]                 = df.index.month
        df["cooling_demand_proxy"] = (df["temp_c"] - setpoint).clip(lower=0)
        df["kwh_rolling_24h"]      = df["kwh"].rolling(24, min_periods=1).mean()
        return df

    def daily_summary(self, df=None):
        if df is None:
            df = self.load()
        return df.resample("1D").agg(
            kwh=("kwh", "sum"),
            temp_max=("temp_c", "max"),
            cooling_proxy=("cooling_demand_proxy", "sum"),
        )
