"""Initialize SQLite, seed config, generate synthetic year, run full agent pipeline.

Idempotent for config (only inserts missing keys); destructive for time-series
and scenario tables (rebuilt on every run). To change a config value at runtime,
use `core.config.put(key, value, type_)` — do not edit DEFAULTS and re-bootstrap.
"""
from core import config
from core.db import init_db
from data import synthetic


def run_optimizer():
    """Strategy → Orchestration → Impact for the top-N anomaly windows.

    Clears existing scenarios/actions/narrations, then writes one scenario row
    per chosen strategy. Returns (n_windows_considered, n_scenarios_written).
    """
    from agents.pattern import PatternAgent
    from agents.strategy import StrategyAgent
    from agents.orchestration import OrchestrationAgent
    from agents.impact import ImpactAgent

    top_n = config.get("demo.top_n_windows")
    windows = PatternAgent().windows(top_n=top_n, kind="emission_peak")
    if not windows:
        return 0, 0

    strat = StrategyAgent()
    candidates_by_window = [
        strat.candidates(w["start"], w["end"]) for w in windows
    ]

    chosen = OrchestrationAgent().optimize(candidates_by_window)
    impact = ImpactAgent()

    n_written = 0
    for i, (_, _, cand) in enumerate(chosen):
        ev = impact.evaluate(cand)
        if ev is None:
            continue
        impact.persist(ev, clear=(n_written == 0))
        n_written += 1
    return len(windows), n_written


def narrate_top_scenario():
    """Run AdvisorAgent on the highest-saving scenario. Returns (id, model)."""
    from core.db import connect
    from agents.advisor import AdvisorAgent

    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM scenarios ORDER BY kg_co2_saved DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None, None
    _, model = AdvisorAgent().narrate(row["id"])
    return row["id"], model


def main():
    print("[1/5] init_db ...")
    init_db()

    print("[2/5] seed config defaults ...")
    config.seed_defaults()

    print("[3/5] generate + dump synthetic year ...")
    n_w, n_c, n_g = synthetic.dump_to_db()
    print(f"       weather:        {n_w} rows")
    print(f"       consumption:    {n_c} rows")
    print(f"       grid_intensity: {n_g} rows")

    print("[4/5] sanity-check pattern detection ...")
    from agents.pattern import PatternAgent
    n_anom = PatternAgent().persist()
    print(f"       anomalies:      {n_anom} rows")

    print("[5/5] run optimizer + impact + narration ...")
    n_win, n_sc = run_optimizer()
    print(f"       windows considered: {n_win}")
    print(f"       scenarios written:  {n_sc}")
    sc_id, model = narrate_top_scenario()
    if sc_id is not None:
        print(f"       top narration:      scenario {sc_id} via {model}")

    print("done.")


if __name__ == "__main__":
    main()
