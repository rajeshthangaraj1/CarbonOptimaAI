import numpy as np
from core import config


def compute(irradiance_wm2, hour_of_day):
    """Hourly UAE grid carbon intensity from irradiance + hour-of-day.

    UAE generation stack: gas baseload + Mohammed bin Rashid solar (variable) +
    Barakah nuclear (~85% capacity factor, treated as flat). Intensity is the
    demand-weighted gas share times gas emission factor; solar and nuclear
    are treated as zero-carbon.

    Returns (intensity, gas_share, solar_share, nuclear_share) as numpy arrays.
    """
    gas_intensity = config.get("grid.gas_intensity")
    solar_cap     = config.get("grid.solar_capacity_mw")
    nuclear_cap   = config.get("grid.nuclear_capacity_mw")
    peak_demand   = config.get("grid.peak_demand_mw")

    hod = np.asarray(hour_of_day, dtype=float)
    irr = np.asarray(irradiance_wm2, dtype=float)

    demand_shape = (
        0.55
        + 0.20 * np.cos(2 * np.pi * (hod - 15) / 24)
        + 0.10 * np.maximum(0.0, np.cos(2 * np.pi * (hod - 9) / 24))
    )
    demand_mw = peak_demand * np.clip(demand_shape, 0.4, 1.0)

    solar_gen = np.minimum(solar_cap * (irr / 950.0) * 0.85, demand_mw)
    nuclear_gen = np.minimum(np.full_like(demand_mw, nuclear_cap * 0.85),
                             demand_mw - solar_gen)
    gas_gen = np.maximum(0.0, demand_mw - solar_gen - nuclear_gen)

    total = gas_gen + solar_gen + nuclear_gen
    gas_share     = gas_gen / total
    solar_share   = solar_gen / total
    nuclear_share = nuclear_gen / total

    intensity = gas_share * gas_intensity
    return intensity, gas_share, solar_share, nuclear_share
