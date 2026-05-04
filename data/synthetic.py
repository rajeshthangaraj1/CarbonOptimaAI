import numpy as np
import pandas as pd

from core import config
from core.db import connect
from models.grid_intensity import compute as compute_grid


def _hour_index():
    start = config.get("synthetic.start")
    end   = config.get("synthetic.end")
    return pd.date_range(start=f"{start} 00:00:00",
                         end=f"{end} 23:00:00", freq="h")


def _weather(idx, seed):
    rng = np.random.default_rng(seed)
    doy = idx.dayofyear.values
    hod = idx.hour.values

    annual = -np.cos(2 * np.pi * (doy - 30) / 365.0)
    season_mean = 28.0 + 12.0 * annual
    diurnal = -np.cos(2 * np.pi * (hod - 4) / 24.0) * 5.0
    temp_c = season_mean + diurnal + rng.normal(0, 1.5, len(idx))

    humidity = np.clip(85.0 - (temp_c - 25.0) * 1.5 + rng.normal(0, 5.0, len(idx)), 20.0, 95.0)

    hour_angle = (hod - 12) * np.pi / 12.0
    solar_factor = np.maximum(0.0, np.cos(hour_angle))
    season_solar = 0.85 + 0.15 * annual
    cloud = rng.uniform(0.7, 1.0, len(idx))
    irradiance = 950.0 * solar_factor * season_solar * cloud

    return pd.DataFrame({
        "ts":             idx.strftime("%Y-%m-%d %H:%M:%S"),
        "temp_c":         np.round(temp_c, 2),
        "humidity":       np.round(humidity, 2),
        "irradiance_wm2": np.round(irradiance, 2),
    })


def _consumption(idx, weather_df, seed):
    rng = np.random.default_rng(seed + 1)
    base_load = config.get("building.base_load_kw")
    setpoint  = config.get("building.cooling_setpoint_c")

    hod = idx.hour.values
    dow = idx.dayofweek.values
    is_weekend = dow >= 5

    delta_t = np.maximum(0.0, weather_df["temp_c"].values - setpoint)
    cooling_load = 1.2 * delta_t

    occ = np.where(
        (hod >= 8) & (hod < 19) & (~is_weekend), 1.5,
        np.where(is_weekend, 0.6, 0.8),
    )

    plug_light = base_load * occ
    kwh = plug_light + cooling_load * (0.7 * occ + 0.3)
    kwh = kwh + rng.normal(0, 0.5, len(idx))
    kwh = np.maximum(kwh, base_load * 0.4)

    return pd.DataFrame({
        "ts":  idx.strftime("%Y-%m-%d %H:%M:%S"),
        "kwh": np.round(kwh, 3),
    })


def _grid_intensity(idx, weather_df, seed):
    rng = np.random.default_rng(seed + 2)
    intensity, gas_s, solar_s, nuclear_s = compute_grid(
        weather_df["irradiance_wm2"].values, idx.hour.values,
    )
    intensity = np.clip(intensity + rng.normal(0, 0.005, len(idx)), 0.05, 0.6)
    return pd.DataFrame({
        "ts":                   idx.strftime("%Y-%m-%d %H:%M:%S"),
        "intensity_kg_per_kwh": np.round(intensity, 4),
        "gas_share":            np.round(gas_s, 4),
        "solar_share":          np.round(solar_s, 4),
        "nuclear_share":        np.round(nuclear_s, 4),
    })


def generate_all():
    seed = config.get("synthetic.seed")
    idx  = _hour_index()
    weather     = _weather(idx, seed)
    consumption = _consumption(idx, weather, seed)
    grid        = _grid_intensity(idx, weather, seed)
    return weather, consumption, grid


def dump_to_db():
    weather, consumption, grid = generate_all()
    with connect() as c:
        c.execute("DELETE FROM weather")
        c.execute("DELETE FROM consumption")
        c.execute("DELETE FROM grid_intensity")
        c.executemany(
            "INSERT INTO weather (ts, temp_c, humidity, irradiance_wm2) VALUES (?, ?, ?, ?)",
            weather.values.tolist(),
        )
        c.executemany(
            "INSERT INTO consumption (ts, kwh) VALUES (?, ?)",
            consumption.values.tolist(),
        )
        c.executemany(
            "INSERT INTO grid_intensity (ts, intensity_kg_per_kwh, gas_share, solar_share, nuclear_share) "
            "VALUES (?, ?, ?, ?, ?)",
            grid.values.tolist(),
        )
    return len(weather), len(consumption), len(grid)
