import json
from .db import connect

DEFAULTS = {
    "timezone":                       ("Asia/Dubai",            "str"),
    "weather.lat":                    (25.2048,                 "float"),
    "weather.lon":                    (55.2708,                 "float"),
    "building.id":                    ("DXB-OFFICE-001",        "str"),
    "building.area_sqm":              (2000.0,                  "float"),
    "building.base_load_kw":          (5.0,                     "float"),
    "building.cooling_setpoint_c":    (24.0,                    "float"),
    "building.thermal_inertia_hr":    (2.5,                     "float"),
    "building.comfort_band_c":        (1.5,                     "float"),
    "grid.gas_intensity":             (0.50,                    "float"),
    "grid.solar_capacity_mw":         (5000.0,                  "float"),
    "grid.nuclear_capacity_mw":       (5600.0,                  "float"),
    "grid.peak_demand_mw":            (14000.0,                 "float"),
    "synthetic.start":                ("2025-01-01",            "str"),
    "synthetic.end":                  ("2025-12-31",            "str"),
    "synthetic.seed":                 (42,                      "int"),
    "pattern.contamination":          (0.05,                    "float"),
    "cooling.coef_kwh_per_c":         (1.2,                     "float"),
    "orchestration.comfort_budget":   (6.0,                     "float"),
    "impact.bootstrap_n":             (300,                     "int"),
    "impact.delta_noise":             (0.10,                    "float"),
    "impact.intensity_noise":         (0.05,                    "float"),
    "demo.top_n_windows":             (8,                       "int"),
    "llm.provider":                   ("ollama",                "str"),
    "llm.model":                      ("gemma4:e4b",            "str"),
    "llm.ollama_url":                 ("http://localhost:11434","str"),
    "llm.api_key_env":                ("ANTHROPIC_API_KEY",     "str"),
    "llm.timeout_s":                  (60,                      "int"),
    "demo.peak_window_start":         ("14:00",                 "str"),
    "demo.peak_window_end":           ("17:00",                 "str"),
}

_CASTERS = {
    "str":   str,
    "int":   int,
    "float": float,
    "bool":  lambda v: str(v).lower() in ("1", "true", "yes"),
    "json":  json.loads,
}


def seed_defaults():
    with connect() as c:
        existing = {r["key"] for r in c.execute("SELECT key FROM config").fetchall()}
        for key, (val, typ) in DEFAULTS.items():
            if key not in existing:
                c.execute(
                    "INSERT INTO config (key, value, type) VALUES (?, ?, ?)",
                    (key, str(val), typ),
                )


def get(key, default=None):
    with connect() as c:
        row = c.execute(
            "SELECT value, type FROM config WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return default
    return _CASTERS[row["type"]](row["value"])


def put(key, value, type_="str"):
    with connect() as c:
        c.execute(
            "INSERT INTO config (key, value, type) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, type=excluded.type",
            (key, str(value), type_),
        )


def all_():
    with connect() as c:
        rows = c.execute("SELECT key, value, type FROM config").fetchall()
    return {r["key"]: _CASTERS[r["type"]](r["value"]) for r in rows}
