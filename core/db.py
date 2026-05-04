import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "carbon_optima.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    type  TEXT NOT NULL DEFAULT 'str'
);

CREATE TABLE IF NOT EXISTS consumption (
    ts  TEXT PRIMARY KEY,
    kwh REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS weather (
    ts             TEXT PRIMARY KEY,
    temp_c         REAL NOT NULL,
    humidity       REAL NOT NULL,
    irradiance_wm2 REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS grid_intensity (
    ts                   TEXT PRIMARY KEY,
    intensity_kg_per_kwh REAL NOT NULL,
    gas_share            REAL NOT NULL,
    solar_share          REAL NOT NULL,
    nuclear_share        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS anomalies (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    TEXT NOT NULL,
    score REAL NOT NULL,
    kind  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts       TEXT NOT NULL,
    window_start     TEXT NOT NULL,
    window_end       TEXT NOT NULL,
    baseline_kwh     REAL NOT NULL,
    optimized_kwh    REAL NOT NULL,
    baseline_kg_co2  REAL NOT NULL,
    optimized_kg_co2 REAL NOT NULL,
    kg_co2_saved     REAL NOT NULL,
    ci_low           REAL NOT NULL,
    ci_high          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    ts_start    TEXT NOT NULL,
    ts_end      TEXT NOT NULL,
    kwh_delta   REAL NOT NULL,
    chosen      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);

CREATE TABLE IF NOT EXISTS narrations (
    scenario_id INTEGER PRIMARY KEY,
    text        TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_ts  TEXT NOT NULL,
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


def to_records(df):
    return df.values.tolist()
