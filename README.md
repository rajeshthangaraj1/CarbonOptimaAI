# CarbonOptimaAI

Hourly carbon optimization for UAE buildings — an 8-agent pipeline that detects emission peaks on the UAE grid and shifts cooling load against the time-of-day intensity differential.

Built for the **DEWA CleanTech Hackathon 2026**. Aligned with the UAE Net Zero 2050 strategy: every kWh of building load is scored against the *actual hourly* mix of gas, MBR solar, and Barakah nuclear — not a flat emission factor.

> See [`PROPOSAL.md`](PROPOSAL.md) for the full hackathon submission (problem, differentiation, agent roster, build plan, demo flow).

## What it does

1. Ingests a year of hourly building consumption + UAE weather + grid intensity (synthetic in v1, swappable for bayanat.ae).
2. Detects anomalous emission peaks using an Isolation Forest over (kwh, temperature, cooling demand proxy, grid intensity, kg CO₂).
3. Generates 4 candidate strategies per peak window — conservative / standard / aggressive pre-cool, plus pure setback.
4. Picks the optimal mix with a binary integer LP (pulp CBC) under a global comfort budget.
5. Quantifies counterfactual savings with a 300-sample bootstrap CI over actuator + intensity-forecast noise.
6. Narrates the chosen plan in plain English via Claude (template fallback when no API key).

The "moat" is in step 4: a real optimizer, not an LLM rules-wrapper. The LLM only narrates — it never decides.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bootstrap.py            # init DB, generate 1yr of data, run full pipeline
.venv/bin/streamlit run app.py           # launch dashboard
```

Optional: `export ANTHROPIC_API_KEY=...` for real Claude narration. Without it, the Advisor tab uses a deterministic template — the demo never depends on network state.

## Dashboard

Four tabs:

- **Live state** — UAE grid intensity gauge, generation mix donut, 3-axis daily timeline (kWh / intensity / kg CO₂) with anomaly markers.
- **Anomalies** — month × hour heatmap of anomaly score density + raw table.
- **Scenarios** — pick a scenario; see before/after CO₂ timeline, per-hour action bars, savings + 95% CI.
- **Advisor** — cached Claude narration of the chosen plan; on-demand regeneration.

Sidebar **Re-run optimizer** replays Strategy → Orchestration → Impact without rebuilding synthetic data.

## Architecture in one paragraph

Single SQLite database (`data/carbon_optima.db`) is the source of truth. Agents communicate by reading/writing tables, never by passing DataFrames. Configuration is data — no `.env`, no settings module — values live in the `config` table and are seeded once from `core/config.DEFAULTS`. The grid intensity model (`models/grid_intensity.py`) is shared between historical scoring and forecast scoring so synthetic and real-time paths stay aligned.

## Agent pipeline

| # | Agent          | Reads                                   | Writes               |
|---|----------------|-----------------------------------------|----------------------|
| 1 | Energy         | `consumption`, `weather`                | features (in-memory) |
| 2 | Carbon         | `consumption`, `grid_intensity`         | kg CO₂ per hour      |
| 3 | Pattern        | features                                | `anomalies`          |
| 4 | Cooling        | `config` (thermal coef, comfort band)   | candidate actions    |
| 5 | Strategy       | `grid_intensity`, candidates            | scored candidates    |
| 6 | Orchestration  | scored candidates                       | chosen plan (LP)     |
| 7 | Impact         | `consumption`, `grid_intensity`, plan   | `scenarios`, `actions` |
| 8 | Advisor        | `scenarios`, `actions`, `config`        | `narrations`         |

Run any agent standalone in a notebook — they all read inputs from SQLite.

## Project layout

```
agents/         # 8-agent pipeline (one file per agent)
core/           # db.py (SCHEMA), config.py (DB-backed settings)
data/           # synthetic.py + carbon_optima.db (created on bootstrap)
models/         # grid_intensity.py — shared UAE generation-mix model
app.py          # Streamlit dashboard
bootstrap.py    # init + run full pipeline; exposes run_optimizer() for the dashboard
PROPOSAL.md     # hackathon submission
CLAUDE.md       # contributor guide for Claude Code
```

## Configuration

Tunables live in the `config` table (seeded from `core/config.DEFAULTS`):

- `building.area_sqm`, `building.cooling_setpoint_c`, `building.comfort_band_c`
- `cooling.coef_kwh_per_c` — kWh per 1°C of pre-cool depth
- `orchestration.comfort_budget` — global cap on summed comfort cost
- `impact.bootstrap_n`, `impact.delta_noise`, `impact.intensity_noise`
- `llm.model`, `llm.api_key_env` — name of the env var holding the key (the key itself is never stored in the DB)
- `demo.top_n_windows` — how many peak windows to optimize per run

To change a value at runtime: `core.config.put("key", value, "type_")`. Don't edit `DEFAULTS` and re-bootstrap — seeding only inserts missing keys.

## Stack

Python 3.10+, pandas, numpy, scikit-learn (Isolation Forest), pulp + CBC (LP), Streamlit + Plotly (UI), anthropic (narration), SQLite (storage).
