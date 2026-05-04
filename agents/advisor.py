import os
from datetime import datetime, timezone

from core import config
from core.db import connect

TS_FMT = "%Y-%m-%d %H:%M:%S"


class AdvisorAgent:
    """Narrates a chosen scenario in plain English. Uses Claude if an API
    key is available; otherwise falls back to a deterministic template so
    the demo never depends on network state.

    Per PROPOSAL.md §3, the LLM only narrates — it never decides. Inputs
    are the scenario row + chosen actions; output is 2-3 short paragraphs.
    """

    def __init__(self, force_template=False):
        self.force_template = force_template
        self.model          = config.get("llm.model")
        self.api_key_env    = config.get("llm.api_key_env")

    def narrate(self, scenario_id):
        ctx = self._fetch(scenario_id)
        if self.force_template or not self._api_key():
            text, model = self._template(ctx), "template"
        else:
            try:
                text, model = self._claude(ctx), self.model
            except Exception as e:
                text, model = self._template(ctx) + f"\n\n(LLM fallback: {type(e).__name__})", "template"
        self._save(scenario_id, text, model)
        return text, model

    def _api_key(self):
        return os.environ.get(self.api_key_env, "").strip() or None

    def _fetch(self, scenario_id):
        with connect() as conn:
            sc = conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            if sc is None:
                raise ValueError(f"scenario {scenario_id} not found")
            actions = conn.execute(
                "SELECT kind, ts_start, ts_end, kwh_delta FROM actions "
                "WHERE scenario_id = ? ORDER BY ts_start",
                (scenario_id,),
            ).fetchall()
        return {
            "scenario": dict(sc),
            "actions":  [dict(a) for a in actions],
            "building": {
                "id":       config.get("building.id"),
                "area_sqm": config.get("building.area_sqm"),
                "setpoint": config.get("building.cooling_setpoint_c"),
                "band":     config.get("building.comfort_band_c"),
            },
        }

    def _template(self, ctx):
        s = ctx["scenario"]
        actions = ctx["actions"]
        b = ctx["building"]

        kinds = sorted({a["kind"] for a in actions})
        precool = [a for a in actions if a["kind"] == "pre_cool"]
        coast   = [a for a in actions if a["kind"] == "coast"]
        setback = [a for a in actions if a["kind"] == "setback"]

        save_pct = (s["kg_co2_saved"] / s["baseline_kg_co2"] * 100.0) if s["baseline_kg_co2"] else 0.0

        plan_line = ", ".join(kinds)
        if precool and coast:
            mech = (
                f"The plan pre-cools the building for {len(precool)} hours immediately "
                f"before the peak (consuming {sum(a['kwh_delta'] for a in precool):.1f} extra "
                f"kWh while grid intensity is low) and then coasts on stored thermal mass "
                f"through the {len(coast)}-hour peak window (avoiding "
                f"{abs(sum(a['kwh_delta'] for a in coast)):.1f} kWh while intensity is high)."
            )
        elif setback:
            mech = (
                f"The plan applies a setpoint setback during the {len(setback)}-hour peak, "
                f"trimming {abs(sum(a['kwh_delta'] for a in setback)):.1f} kWh of cooling "
                f"load while intensity is at its worst."
            )
        else:
            mech = "The plan reshapes load across the peak window."

        return (
            f"For building {b['id']} ({b['area_sqm']:.0f} m², setpoint {b['setpoint']}°C "
            f"± {b['band']}°C), the orchestrator selected a {plan_line} strategy for the "
            f"window {s['window_start']} → {s['window_end']}.\n\n"
            f"{mech} Net consumption shifts but stays close to the baseline "
            f"({s['baseline_kwh']:.1f} → {s['optimized_kwh']:.1f} kWh).\n\n"
            f"Counterfactual savings: {s['kg_co2_saved']:.2f} kg CO₂ "
            f"({save_pct:.1f}% of the do-nothing baseline), with a 95% bootstrap CI of "
            f"[{s['ci_low']:.2f}, {s['ci_high']:.2f}] kg. The CI accounts for both "
            f"actuator execution noise and grid intensity forecast error."
        )

    def _claude(self, ctx):
        import anthropic
        s = ctx["scenario"]
        b = ctx["building"]
        action_lines = "\n".join(
            f"  - {a['kind']:<10} {a['ts_start']} → {a['ts_end']}  Δ={a['kwh_delta']:+.2f} kWh"
            for a in ctx["actions"]
        )

        prompt = (
            "You are a clean-energy operations advisor narrating a chosen carbon-optimization plan. "
            "Write 2-3 short paragraphs (about 150 words total) in clear, confident operator English. "
            "Do NOT recommend changes — the optimizer has already decided. Explain WHY the plan saves "
            "carbon, naming the time-of-day intensity differential as the mechanism. End with the "
            "counterfactual saving and its 95% CI.\n\n"
            f"Building: {b['id']} ({b['area_sqm']:.0f} m²), setpoint {b['setpoint']}°C ± {b['band']}°C\n"
            f"Window:   {s['window_start']} → {s['window_end']}\n"
            f"Baseline:    {s['baseline_kwh']:.1f} kWh / {s['baseline_kg_co2']:.2f} kg CO₂\n"
            f"Optimized:   {s['optimized_kwh']:.1f} kWh / {s['optimized_kg_co2']:.2f} kg CO₂\n"
            f"Saved:       {s['kg_co2_saved']:.2f} kg CO₂  (95% CI [{s['ci_low']:.2f}, {s['ci_high']:.2f}])\n"
            f"Chosen actions:\n{action_lines}\n"
        )

        client = anthropic.Anthropic(api_key=self._api_key())
        resp = client.messages.create(
            model=self.model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()

    def _save(self, scenario_id, text, model):
        with connect() as conn:
            conn.execute(
                "INSERT INTO narrations (scenario_id, text, model, created_ts) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(scenario_id) DO UPDATE SET "
                "text=excluded.text, model=excluded.model, created_ts=excluded.created_ts",
                (scenario_id, text, model,
                 datetime.now(timezone.utc).strftime(TS_FMT)),
            )
