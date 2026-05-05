# CarbonOptimaAI — Project Explanation

A walkthrough of the project from zero, in plain English. Read this top-to-bottom and you should have a clear picture of **what problem we're solving**, **what data we used**, **what each piece of code does**, and **how it all fits together**.

---

## 1. The problem we're solving

The UAE wants to be Net Zero by 2050. To get there, every building needs to use less carbon — not just less electricity. Those are different things.

Why? Because the **carbon emitted per kWh changes hour by hour**.
- Around midday, MBR Solar Park dumps cheap, clean electrons into the grid → low carbon per kWh.
- Around 6 PM, the sun is gone but everyone still has AC running → gas plants ramp up → high carbon per kWh.

So a building that runs 100 kWh at noon and a building that runs 100 kWh at 6 PM use the **same electricity** but emit **very different amounts of CO₂**.

Most "smart building" tools ignore this. They use a flat number like "0.4 kg CO₂ per kWh" and call it a day. That's wrong for the UAE — and it hides the biggest lever a building has: **shifting load in time**.

**Our claim:** if we know the hourly carbon intensity of the grid, and we know how a building's cooling system behaves, we can shift cooling work into the clean-grid hours and coast through the dirty-grid hours — and prove the savings with statistics, not vibes.

That's what this project does.

---

## 2. The big idea, in one sentence

> Detect dirty-grid emission peaks → plan a thermal-mass shift around them → pick the best plan with an optimizer → measure the counterfactual savings with confidence intervals → narrate the decision in English.

The reason there are 8 agents is that each step has its own job. The reason we use a real optimizer (not an LLM) is that the optimizer is the part that's hard and that judges actually trust. The LLM only narrates the answer in plain language at the end.

---

## 3. What data we needed

Three hourly time series for one building, for one full year (8760 hours):

| Data           | What it is                                    | Where it would come from in production |
|----------------|-----------------------------------------------|----------------------------------------|
| **consumption** | kWh used by the building each hour            | bayanat.ae / DEWA smart meter feed     |
| **weather**     | Outdoor temperature & humidity each hour      | NCM (UAE National Center of Meteorology) |
| **grid_intensity** | kg CO₂ per kWh on the UAE grid each hour | Computed from real-time gas / solar / nuclear share |

We don't have live access to those feeds yet, so for the demo we **generated synthetic UAE-shaped data**. The synthetic generator is calibrated to behave like the real thing:
- **Summer (Jul–Aug) consumes ~5× winter** — that's the AC-driven UAE pattern.
- **Hourly intensity peaks at 18:00** — sun gone, AC still running, gas plants pushing hardest.
- **Intensity dips 09:00–11:00** — solar share is highest here.

When real bayanat.ae data shows up, we drop it into the same `consumption` and `weather` tables and the rest of the project doesn't care.

The grid intensity model itself (`models/grid_intensity.py`) is real physics — gas baseload, MBR Solar 5000 MW capacity, Barakah nuclear 5600 MW at ~85% capacity factor. It's the same module used to generate the synthetic year and to score future hours.

---

## 4. How we structured everything

Two structural decisions drive the whole codebase:

### Decision 1: One SQLite database is the source of truth

Everything — input data, configuration, agent outputs, scenarios, narrations — lives in **one file**: `data/carbon_optima.db`.

Agents do **not** pass big DataFrames to each other in memory. Each agent:
1. **Reads** what it needs from a SQLite table.
2. **Writes** its outputs back to a SQLite table.

Why? Because:
- Any agent can run standalone in a notebook for debugging — no need to spin up the whole pipeline.
- The dashboard reads from the same tables without knowing which agent produced what.
- We never lose state. If the laptop dies mid-pipeline, we can resume.

The schema lives in one place: `core/db.py` (the `SCHEMA` constant). New tables are added there, never via ad-hoc `CREATE TABLE` calls scattered around.

### Decision 2: Configuration is data, not code

There's no `.env` file, no `settings.py` with hardcoded values. Every tunable parameter — building floor area, cooling setpoint, comfort band, comfort budget, bootstrap sample count, LLM model name, demo peak window — is a row in the `config` table.

The first time you run `bootstrap.py`, it seeds the table from `core/config.DEFAULTS`. After that, you change values with `core.config.put("key", value, "type_")` from a Python shell. **Don't edit `DEFAULTS` and re-bootstrap** — seeding only inserts missing keys, so your changes won't take effect.

The one exception: the LLM API key. Putting an API key in a SQLite file is bad practice, so the config table only stores the **name of the env var to read** (`llm.api_key_env` = `"ANTHROPIC_API_KEY"`). The key itself stays in your shell.

---

## 5. The agent pipeline, step by step

There are 8 agents. They run in order. Each one's output is the next one's input.

### Agent 1 — EnergyAgent (`agents/energy.py`)
**What it does:** Loads consumption + weather, joins them by timestamp, and builds simple features that the anomaly detector will use later — hour-of-day, day-of-week, a "cooling demand proxy" (basically how much the AC is fighting the heat), and rolling averages.

**Reads:** `consumption`, `weather` tables.
**Writes:** Nothing — its output is held in memory and handed to the Carbon Agent.

**Plain-English summary:** "Here's how much electricity the building used and what the weather was like, side by side, with a few extra columns that make patterns easier to spot."

### Agent 2 — CarbonAgent (`agents/carbon.py`)
**What it does:** Multiplies hourly kWh by hourly grid intensity to get hourly kg CO₂.

**Reads:** `consumption`, `grid_intensity` tables.
**Writes:** Adds a `kg_co2` column to the working frame.

**Plain-English summary:** "100 kWh at noon ≠ 100 kWh at 6 PM in carbon terms. Here's the actual carbon number for every hour."

### Agent 3 — PatternAgent (`agents/pattern.py`)
**What it does:** Runs an Isolation Forest (a sklearn anomaly detection algorithm) over the joined data to flag the worst ~5% of hours. It tags two kinds of anomalies:
- `emission_peak` — top 5% of `kg_co2`. These are the hours that hurt most.
- `consumption_spike` — unusually high kWh, regardless of intensity.

It also has a `windows()` method that groups consecutive bad hours into **windows** (e.g. "2025-08-07 14:00 → 19:00 was a 5-hour emission peak"). The optimizer works on windows, not individual hours.

**Reads:** features from EnergyAgent + CarbonAgent.
**Writes:** `anomalies` table — one row per flagged hour with score and kind.

**Plain-English summary:** "Out of 8760 hours in the year, here are the ~400 worst ones, grouped into the ~8 worst time windows."

### Agent 4 — CoolingAgent (`agents/cooling.py`)
**What it does:** Generates **hourly action plans** for a given window. Two kinds of plans:

- **Pre-cool plan** — for `lookback_hr` hours **before** the peak, run the AC harder than normal (positive `kwh_delta`). This drops the building's internal temperature below setpoint, building up "stored cool" in the thermal mass (walls, floor, furniture). Then during the peak window, **coast** — let the AC do less because the building is already cold (negative `kwh_delta`).
- **Setback plan** — no pre-cool. Just relax the setpoint during the peak (negative `kwh_delta` only).

The total kWh is roughly zero for pre-cool plans — we don't use less electricity overall. The carbon win comes purely from **moving the work to a cleaner-grid hour**.

**Reads:** config (thermal coefficient, comfort band).
**Writes:** Returns a list of action dicts (kind, ts_start, ts_end, kwh_delta).

**Plain-English summary:** "Here's how much extra cooling I can stash in the thermal mass beforehand, and how much I can coast during the peak."

### Agent 5 — StrategyAgent (`agents/strategy.py`)
**What it does:** For each peak window, generates **4 candidate strategies** of varying aggressiveness:
1. `conservative_precool` — small pre-cool, 2 hours of lookback, low comfort cost.
2. `standard_precool` — comfort-band depth, 3 hours of lookback.
3. `aggressive_precool` — 1.3× comfort band, 4 hours of lookback. Higher comfort cost.
4. `setback_only` — no pre-cool, just setback during the peak.

For every candidate, it computes how much CO₂ the candidate would save by **joining each action's hour to the actual hourly grid intensity from the DB**. This is the part that makes our scoring honest — savings depend on *which hour* the action lands on, not a flat factor.

**Reads:** `grid_intensity` table.
**Writes:** Returns a list of scored candidate dicts (kg_co2_saved, kwh_net, comfort_cost).

**Plain-English summary:** "For this peak window, here are 4 things we *could* do, and here's how much CO₂ each one would save against the real hourly grid mix."

### Agent 6 — OrchestrationAgent (`agents/orchestration.py`) — the innovation core
**What it does:** Picks the best mix of strategies across **all** windows at once.

Why "across all windows"? Because we have a global **comfort budget**. Aggressive plans are expensive in comfort; if we use aggressive everywhere we'll annoy the occupants. The optimizer's job is to spread the comfort budget across the year intelligently — e.g. spend it on the windows where the carbon win is biggest.

It uses **pulp + CBC** to solve a binary integer linear program:
- **Variables:** `x[w, k] ∈ {0, 1}` — should we pick candidate `k` for window `w`?
- **Objective:** maximize total CO₂ saved.
- **Constraint 1:** at most one candidate per window.
- **Constraint 2:** total comfort cost ≤ `orchestration.comfort_budget`.
- **Constraint 3:** never pick a candidate with negative savings.

If pulp/CBC isn't installed or the LP fails, it silently falls back to a greedy ratio-rank: sort candidates by `savings / comfort_cost`, take in order until the budget runs out.

**Reads:** the candidates from StrategyAgent.
**Writes:** Returns the chosen list — `(window_idx, candidate_idx, candidate_dict)` tuples.

**Plain-English summary:** "Out of all the candidate strategies for all the peak windows, here's the combination that saves the most CO₂ without exceeding our comfort budget."

This is the part PROPOSAL.md calls the moat. It's why "LLM wrapper called multi-agent" doesn't compete with us — the optimizer does the actual decision math.

### Agent 7 — ImpactAgent (`agents/impact.py`)
**What it does:** Two jobs.

**Job 1 — counterfactual.** "Baseline" is what the building *would* have done with no intervention (just the actual `kwh × intensity` for those hours). "Optimized" applies our action deltas. Subtract → kg CO₂ saved.

**Job 2 — confidence interval.** A point estimate ("we saved 1.70 kg") isn't enough — anyone savvy will ask "with what uncertainty?" So we run a 300-sample bootstrap with two noise sources:
- **Actuator noise** — we asked for a `kwh_delta` of X, but real HVAC equipment delivers `X × (1 + ε)`.
- **Intensity noise** — the grid intensity at execution time differs slightly from the modeled value.

For each of the 300 samples we re-roll both jitters and recompute the savings. We then take the 2.5th and 97.5th percentiles → that's the **95% CI**.

**Reads:** `consumption`, `grid_intensity` tables.
**Writes:** One row per chosen strategy in `scenarios` (with kg_co2_saved, ci_low, ci_high) + N rows per scenario in `actions`.

**Plain-English summary:** "If we executed this plan, we'd save 1.70 kg CO₂, and we're 95% confident the real number lands between 1.49 and 1.93 kg."

### Agent 8 — AdvisorAgent (`agents/advisor.py`)
**What it does:** Turns a chosen scenario into 2–3 paragraphs of plain English so a building operator can read it and understand *why* the plan saves carbon.

If `ANTHROPIC_API_KEY` is set, it calls the Claude API. Otherwise, it falls back to a deterministic template — **the demo never depends on network state**. This was a deliberate choice: hackathon Wi-Fi can't be trusted.

Per the proposal, the LLM **only narrates** — it never decides. The optimizer already made the decision; the LLM just explains it.

**Reads:** `scenarios`, `actions`, `config` tables.
**Writes:** One row in `narrations` per scenario (UPSERT keyed by scenario_id, so re-narrating overwrites).

**Plain-English summary:** "The optimizer picked Plan B for this window. Here's a paragraph explaining why that plan saves CO₂, what it does hour by hour, and the confidence interval on the savings — so a non-technical operator can sign off."

---

## 6. How it all chains together — `bootstrap.py`

`bootstrap.py` is the entry point. Running it does five steps:

```
[1/5] init_db                 → create tables (idempotent)
[2/5] seed config defaults    → insert missing config keys
[3/5] generate synthetic year → 8760 rows each in weather, consumption, grid_intensity
[4/5] sanity-check pattern    → run PatternAgent, write anomalies table
[5/5] run optimizer pipeline  → Strategy → Orchestration → Impact → Advisor
```

A few things worth knowing:

- **Idempotent for config, destructive for time-series.** Running `bootstrap.py` twice is safe for config (it skips existing keys) but **wipes and rebuilds** the time-series tables and scenarios. That's deliberate — synthetic data is supposed to be reproducible.
- **`run_optimizer()` is exposed as a function** so the dashboard's "Re-run optimizer" button can replay just the decision layer (steps 4–5) without rebuilding the synthetic year.
- **`narrate_top_scenario()` is also exposed** for the dashboard's "Re-narrate top scenario" button.

End-to-end run on a fresh DB:
```
weather: 8760, consumption: 8760, grid_intensity: 8760
anomalies: 438 rows
windows considered: 8, scenarios written: 8
top narration: scenario 1 via template
```

The top scenario was: 2025-08-07 14:00→19:00, baseline 56.39 kg CO₂ → optimized 54.69 kg → **saved 1.70 kg with 95% CI [1.49, 1.93]**, executed via 3 hours of pre-cool + 6 hours of coast.

---

## 7. The dashboard — `app.py`

A Streamlit app with four tabs and a sidebar.

**Tab 1 — Live state.** A snapshot of "right now" (or any picked day):
- A gauge showing current grid intensity in kg CO₂/kWh.
- A donut showing the live generation mix (gas / solar / nuclear).
- A 3-axis timeline: kWh consumption, grid intensity, kg CO₂ — for the picked day, with anomaly markers as vertical lines.

**Tab 2 — Anomalies.** A bird's-eye view of the year's bad hours:
- KPIs: total anomalies, hours flagged, peak hour of day.
- A month × hour heatmap of anomaly score density (so you can see "August at 6 PM is the danger zone" at a glance).
- The raw anomalies table.

**Tab 3 — Scenarios.** The decision layer made human-readable:
- Selectbox over the 8 scenarios (sorted by savings).
- Before/after CO₂ timeline for the chosen window.
- Per-hour bar chart of pre_cool / coast / setback actions.
- The savings number with its 95% CI.

**Tab 4 — Advisor.** The narration tab:
- Renders the cached narration text from the `narrations` table.
- A "Generate narration" button that calls AdvisorAgent on demand.

**Sidebar.** Two write actions:
- **Re-run optimizer** → calls `bootstrap.run_optimizer()`, clears Streamlit's cache, reruns the page.
- **Re-narrate top scenario** → calls `bootstrap.narrate_top_scenario()`, same cache-clear-then-rerun.

The cache invalidation pattern is important: every read goes through `@st.cache_data(ttl=...)`, so after writing to the DB you have to `st.cache_data.clear()` and `st.rerun()` or the UI shows stale data. This is the kind of bug that bites Streamlit demos five minutes before the judges arrive.

---

## 8. Color-coded design choices (and why)

A few decisions you might wonder about while reading the code:

- **Why SQLite, not Postgres or DataFrames?** Hackathon timeline. SQLite means zero setup, the DB ships with the repo, and every read/write is one line of code. Production would swap it for Postgres or BigQuery; the agent contract doesn't change.
- **Why one big repo, not microservices?** PROPOSAL.md §7 explicitly forbids it. Microservices for a hackathon = wasted hours on Docker and not on the actual product.
- **Why an Isolation Forest, not a deep model?** The data is hourly tabular. Isolation Forest is the right tool, trains in milliseconds, and is interpretable. Anything fancier would be cargo-cult ML.
- **Why pulp + CBC for the LP?** It's the open-source LP solver everyone has heard of, it's pip-installable, and the problem is tiny (8 windows × 4 candidates = 32 binary variables — solves in milliseconds).
- **Why a bootstrap CI, not a closed-form one?** The two noise sources interact non-linearly through the savings formula. Bootstrapping is the honest answer; closed-form would require strong assumptions we can't defend.
- **Why two write actions in the sidebar instead of one?** Demo theatre. The "Re-run optimizer" button visibly recomputes scenarios; the "Re-narrate" button visibly hits Claude. Judges see the agents working live.
- **Why the API key isn't in the DB?** Because anyone who looks at the file would see it. The DB stores the *name* of the env var. The key itself only lives in your shell.

---

## 9. How to run it from scratch

```bash
# one-time setup
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# run the full pipeline (writes data/carbon_optima.db)
.venv/bin/python bootstrap.py

# launch the dashboard
.venv/bin/streamlit run app.py
```

Optional: `export ANTHROPIC_API_KEY=...` before launching streamlit if you want real Claude narrations. Without it, the Advisor tab uses the template — and the template is good enough that the demo holds up.

---

## 10. What's not real (yet) and what would change

**Not real today (synthetic):**
- Building consumption — drawn from a UAE-shaped synthetic generator.
- Weather — same.
- Grid intensity — computed from the real UAE generation-mix model, but using synthetic generation profiles.

**What changes when real data arrives:**
- `data/synthetic.py` is replaced with a `data/bayanat.py` (or similar) that fetches real consumption + weather and writes it to the same `consumption` and `weather` tables.
- `models/grid_intensity.py` either (a) keeps generating intensity from the live mix or (b) is replaced with a feed from a UAE TSO API.
- **No agent changes.** That's the whole point of the SQLite-as-contract design.

**What's deliberately out of scope (PROPOSAL.md §12):**
- Multi-building / district-level optimization.
- Live actuator control (we generate plans, we don't push them to BMS systems).
- Forecasting next-24h intensity (the model can do it; we don't surface it in v1).

---

## 11. The shortest possible summary

> We built an 8-agent pipeline that finds the dirtiest hours on the UAE grid, plans cooling shifts around them, picks the best plan with a real optimizer, quantifies savings with a confidence interval, and explains the decision in English. Everything talks through one SQLite file. The optimizer is the moat; the LLM is decoration.

If you've read this far, you have the full picture. The code is small enough to read in an afternoon — start with `bootstrap.py`, then walk down `agents/` in order, then look at `app.py`. Anything that surprises you is documented either here, in `CLAUDE.md`, or in `PROPOSAL.md`.
