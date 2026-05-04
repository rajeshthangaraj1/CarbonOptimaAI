"""CarbonOptimaAI — Streamlit dashboard.

Reads from data/carbon_optima.db. Run:
    .venv/bin/streamlit run app.py

The dashboard is read-only by default. The sidebar has two write actions:
"Re-run optimizer" replays Strategy → Orchestration → Impact for the top-N
anomaly windows; "Re-narrate top scenario" calls AdvisorAgent (Claude API
if ANTHROPIC_API_KEY is set, deterministic template otherwise).
"""
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import config
from core.db import connect

st.set_page_config(
    page_title="CarbonOptimaAI",
    page_icon="🌿",
    layout="wide",
)

PRIMARY = "#2E7D32"
ACCENT  = "#FFA000"
PEAK    = "#C62828"


@st.cache_data(ttl=60)
def load_consumption():
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT ts, kwh FROM consumption ORDER BY ts",
            conn, parse_dates=["ts"],
        ).set_index("ts")


@st.cache_data(ttl=60)
def load_weather():
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT ts, temp_c, humidity, irradiance_wm2 FROM weather ORDER BY ts",
            conn, parse_dates=["ts"],
        ).set_index("ts")


@st.cache_data(ttl=60)
def load_grid():
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT ts, intensity_kg_per_kwh, gas_share, solar_share, nuclear_share "
            "FROM grid_intensity ORDER BY ts",
            conn, parse_dates=["ts"],
        ).set_index("ts")


@st.cache_data(ttl=30)
def load_anomalies():
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT ts, score, kind FROM anomalies ORDER BY ts",
            conn, parse_dates=["ts"],
        )


@st.cache_data(ttl=30)
def load_scenarios():
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT * FROM scenarios ORDER BY kg_co2_saved DESC", conn,
            parse_dates=["created_ts", "window_start", "window_end"],
        )


@st.cache_data(ttl=30)
def load_actions(scenario_id):
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT kind, ts_start, ts_end, kwh_delta FROM actions "
            "WHERE scenario_id = ? ORDER BY ts_start",
            conn, params=(int(scenario_id),),
            parse_dates=["ts_start", "ts_end"],
        )


@st.cache_data(ttl=30)
def load_narration(scenario_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT text, model, created_ts FROM narrations WHERE scenario_id = ?",
            (int(scenario_id),),
        ).fetchone()
    return dict(row) if row else None


def daily_frame(date):
    cons = load_consumption()
    grid = load_grid()
    wx   = load_weather()
    day = pd.Timestamp(date)
    mask_c = (cons.index.date == day.date())
    mask_g = (grid.index.date == day.date())
    mask_w = (wx.index.date == day.date())
    df = cons[mask_c].join(grid[mask_g], how="inner").join(wx[mask_w], how="inner")
    df["kg_co2"] = df["kwh"] * df["intensity_kg_per_kwh"]
    return df


def kpi(label, value, hint=None):
    st.metric(label, value, hint)


def fig_intensity_gauge(value, gas_share, solar_share, nuclear_share):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(value),
        number={"suffix": " kg/kWh", "valueformat": ".3f"},
        title={"text": "Current grid intensity"},
        gauge={
            "axis":      {"range": [0, 0.5]},
            "bar":       {"color": PRIMARY},
            "steps":     [
                {"range": [0.00, 0.15], "color": "#C8E6C9"},
                {"range": [0.15, 0.30], "color": "#FFE0B2"},
                {"range": [0.30, 0.50], "color": "#FFCDD2"},
            ],
        },
    ))
    fig.update_layout(height=250, margin=dict(l=10, r=10, t=40, b=10))
    return fig


def fig_mix_donut(gas_share, solar_share, nuclear_share):
    fig = go.Figure(go.Pie(
        labels=["Gas", "Solar", "Nuclear"],
        values=[gas_share, solar_share, nuclear_share],
        hole=0.55,
        marker_colors=["#8D6E63", "#FFA000", "#1976D2"],
    ))
    fig.update_layout(
        title="Generation mix (this hour)",
        height=250, margin=dict(l=10, r=10, t=40, b=10),
        showlegend=True,
    )
    return fig


def fig_day_timeline(df, anomalies_for_day=None):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["kwh"], name="kWh",
        line=dict(color=PRIMARY, width=2), yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["intensity_kg_per_kwh"], name="grid kg/kWh",
        line=dict(color=ACCENT, width=2, dash="dot"), yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["kg_co2"], name="kg CO₂",
        line=dict(color=PEAK, width=2), yaxis="y3",
    ))
    if anomalies_for_day is not None and len(anomalies_for_day):
        for ts in anomalies_for_day["ts"]:
            fig.add_vline(x=ts, line=dict(color=PEAK, width=1, dash="dot"), opacity=0.3)
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(title="hour"),
        yaxis=dict(title="kWh", side="left"),
        yaxis2=dict(title="kg/kWh", overlaying="y", side="right",
                    showgrid=False, position=0.95),
        yaxis3=dict(title="kg CO₂", overlaying="y", side="right",
                    showgrid=False, anchor="free", position=1.0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def fig_before_after(scenario_row, actions_df):
    ws = pd.Timestamp(scenario_row["window_start"])
    we = pd.Timestamp(scenario_row["window_end"])
    span_start = min(ws, actions_df["ts_start"].min()) if len(actions_df) else ws
    span_end   = max(we, actions_df["ts_end"].max()) if len(actions_df) else we
    cushion = pd.Timedelta(hours=1)

    cons = load_consumption()
    grid = load_grid()
    df = cons.join(grid, how="inner")
    df["kg_co2"] = df["kwh"] * df["intensity_kg_per_kwh"]
    df = df.loc[span_start - cushion : span_end + cushion].copy()

    delta = actions_df.set_index("ts_start")["kwh_delta"] if len(actions_df) else pd.Series(dtype=float)
    df["kwh_optimized"] = df["kwh"] + df.index.map(lambda t: float(delta.get(t, 0.0)))
    df["kg_co2_optimized"] = df["kwh_optimized"] * df["intensity_kg_per_kwh"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["kg_co2"], name="baseline kg CO₂",
        line=dict(color=PEAK, width=2),
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["kg_co2_optimized"], name="optimized kg CO₂",
        line=dict(color=PRIMARY, width=2, dash="dash"),
    ))
    fig.add_vrect(
        x0=ws, x1=we, fillcolor=PEAK, opacity=0.08, line_width=0,
        annotation_text="peak window", annotation_position="top left",
    )
    fig.update_layout(
        height=380, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_title="hour", yaxis_title="kg CO₂",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def fig_action_bars(actions_df):
    if not len(actions_df):
        return None
    colors = actions_df["kind"].map({
        "pre_cool": "#1976D2", "coast": PRIMARY, "setback": ACCENT,
    }).fillna("#757575")
    fig = go.Figure(go.Bar(
        x=actions_df["ts_start"], y=actions_df["kwh_delta"],
        marker_color=colors, text=actions_df["kind"], textposition="outside",
    ))
    fig.update_layout(
        height=240, margin=dict(l=10, r=10, t=30, b=10),
        title="Hourly load deltas (pre-cool +, coast/setback –)",
        xaxis_title="hour", yaxis_title="Δ kWh",
    )
    return fig


def render_sidebar():
    with st.sidebar:
        st.subheader("🏢 Building")
        st.write(f"**ID:** `{config.get('building.id')}`")
        st.write(f"**Area:** {config.get('building.area_sqm'):.0f} m²")
        st.write(f"**Setpoint:** {config.get('building.cooling_setpoint_c')} °C  ± {config.get('building.comfort_band_c')} °C")
        st.write(f"**Base load:** {config.get('building.base_load_kw')} kW")
        st.write(f"**Thermal inertia:** {config.get('building.thermal_inertia_hr')} hr")

        st.divider()
        st.subheader("⚡ Grid mix")
        st.write(f"Gas factor: **{config.get('grid.gas_intensity')} kg/kWh**")
        st.write(f"Solar capacity: **{config.get('grid.solar_capacity_mw'):.0f} MW**")
        st.write(f"Nuclear capacity: **{config.get('grid.nuclear_capacity_mw'):.0f} MW**")

        st.divider()
        st.subheader("🎬 Demo")
        if st.button("Re-run optimizer", type="primary", use_container_width=True):
            with st.spinner("Optimizing top-N anomaly windows..."):
                from bootstrap import run_optimizer
                n_win, n_sc = run_optimizer()
            st.cache_data.clear()
            st.success(f"{n_sc} scenarios written from {n_win} windows")
            st.rerun()

        if st.button("Re-narrate top scenario", use_container_width=True):
            with st.spinner("Generating narration..."):
                from bootstrap import narrate_top_scenario
                sc_id, model = narrate_top_scenario()
            st.cache_data.clear()
            st.success(f"Narration written via {model}")
            st.rerun()

        api_present = bool(os.environ.get(config.get("llm.api_key_env"), "").strip())
        st.caption("LLM: " + ("✅ API key detected" if api_present
                              else f"⚠️ ${config.get('llm.api_key_env')} not set — template narration"))


def tab_live(scenarios):
    cons = load_consumption()
    grid = load_grid()
    wx   = load_weather()

    available_dates = sorted({ts.date() for ts in cons.index})
    if not available_dates:
        st.warning("No data loaded. Run `python bootstrap.py` first.")
        return

    default_date = pd.Timestamp(scenarios.iloc[0]["window_start"]).date() if len(scenarios) else available_dates[180]
    pick = st.date_input(
        "Day to inspect",
        value=default_date,
        min_value=available_dates[0],
        max_value=available_dates[-1],
    )
    df = daily_frame(pick)
    if df.empty:
        st.warning("No data for that day.")
        return

    peak_idx = df["kg_co2"].idxmax()
    peak_row = df.loc[peak_idx]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Day kWh", f"{df['kwh'].sum():.0f}")
    with c2:
        kpi("Day kg CO₂", f"{df['kg_co2'].sum():.1f}")
    with c3:
        kpi("Avg intensity", f"{df['intensity_kg_per_kwh'].mean():.3f} kg/kWh")
    with c4:
        kpi("Peak hour", peak_idx.strftime("%H:%M"),
            hint=f"{peak_row['kg_co2']:.1f} kg CO₂")

    st.divider()
    g1, g2 = st.columns([1, 1])
    with g1:
        st.plotly_chart(
            fig_intensity_gauge(
                peak_row["intensity_kg_per_kwh"],
                peak_row["gas_share"],
                peak_row["solar_share"],
                peak_row["nuclear_share"],
            ),
            use_container_width=True,
        )
    with g2:
        st.plotly_chart(
            fig_mix_donut(
                peak_row["gas_share"],
                peak_row["solar_share"],
                peak_row["nuclear_share"],
            ),
            use_container_width=True,
        )

    anom_df = load_anomalies()
    anom_today = anom_df[anom_df["ts"].dt.date == pick]
    st.plotly_chart(fig_day_timeline(df, anom_today), use_container_width=True)


def tab_anomalies():
    anom = load_anomalies()
    if anom.empty:
        st.info("No anomalies detected. Run `python bootstrap.py` to populate.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi("Anomaly hours", f"{len(anom)}")
    with c2:
        kpi("Emission peaks", f"{(anom['kind'] == 'emission_peak').sum()}")
    with c3:
        kpi("Consumption spikes", f"{(anom['kind'] == 'consumption_spike').sum()}")

    st.divider()
    anom = anom.assign(
        date=anom["ts"].dt.date,
        hour=anom["ts"].dt.hour,
        month=anom["ts"].dt.month,
    )
    pivot = anom.pivot_table(
        index="month", columns="hour", values="score",
        aggfunc="sum", fill_value=0,
    )
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=pivot.columns, y=pivot.index,
        colorscale="OrRd",
    ))
    fig.update_layout(
        height=360, title="Anomaly score density (month × hour)",
        xaxis_title="hour of day", yaxis_title="month",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("All anomalies")
    st.dataframe(
        anom[["ts", "kind", "score"]].sort_values("score", ascending=False),
        use_container_width=True, hide_index=True,
    )


def tab_scenarios(scenarios):
    if scenarios.empty:
        st.info("No scenarios yet. Click **Re-run optimizer** in the sidebar.")
        return

    total_saved = scenarios["kg_co2_saved"].sum()
    total_baseline = scenarios["baseline_kg_co2"].sum()
    save_pct = total_saved / total_baseline * 100.0 if total_baseline else 0.0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Scenarios", f"{len(scenarios)}")
    with c2:
        kpi("Total kg CO₂ saved", f"{total_saved:.2f}")
    with c3:
        kpi("Reduction across windows", f"{save_pct:.1f}%")
    with c4:
        ci_low_sum  = scenarios["ci_low"].sum()
        ci_high_sum = scenarios["ci_high"].sum()
        kpi("95% CI on total", f"[{ci_low_sum:.1f}, {ci_high_sum:.1f}]")

    st.divider()

    display = scenarios.assign(
        label=scenarios.apply(
            lambda r: f"#{r['id']}  {r['window_start']:%Y-%m-%d %H:%M} → "
                      f"{r['window_end']:%H:%M}  ({r['kg_co2_saved']:.2f} kg saved)",
            axis=1,
        ),
    )
    pick_label = st.selectbox("Scenario", display["label"].tolist())
    chosen = display[display["label"] == pick_label].iloc[0]

    actions = load_actions(int(chosen["id"]))

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi("Baseline", f"{chosen['baseline_kg_co2']:.2f} kg")
    with c2:
        kpi("Optimized", f"{chosen['optimized_kg_co2']:.2f} kg")
    with c3:
        kpi(
            "Saved", f"{chosen['kg_co2_saved']:.2f} kg",
            hint=f"95% CI [{chosen['ci_low']:.2f}, {chosen['ci_high']:.2f}]",
        )

    st.plotly_chart(fig_before_after(chosen, actions), use_container_width=True)
    bars = fig_action_bars(actions)
    if bars is not None:
        st.plotly_chart(bars, use_container_width=True)

    with st.expander("Action ledger (raw)"):
        st.dataframe(actions, use_container_width=True, hide_index=True)


def tab_advisor(scenarios):
    if scenarios.empty:
        st.info("No scenarios yet — run the optimizer first.")
        return

    display = scenarios.assign(
        label=scenarios.apply(
            lambda r: f"#{r['id']}  {r['window_start']:%Y-%m-%d}  "
                      f"({r['kg_co2_saved']:.2f} kg saved)",
            axis=1,
        ),
    )
    pick_label = st.selectbox("Scenario", display["label"].tolist())
    chosen = display[display["label"] == pick_label].iloc[0]

    narration = load_narration(int(chosen["id"]))

    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader("Why this plan?")
    with c2:
        if st.button("Generate narration", use_container_width=True):
            with st.spinner("Calling advisor..."):
                from agents.advisor import AdvisorAgent
                AdvisorAgent().narrate(int(chosen["id"]))
            st.cache_data.clear()
            st.rerun()

    if narration is None:
        st.info("No narration yet for this scenario. Click **Generate narration**.")
        return

    badge = "🤖 LLM" if narration["model"] != "template" else "📝 Template"
    st.caption(f"{badge} · model `{narration['model']}` · generated {narration['created_ts']}")
    st.markdown(narration["text"])


def main():
    st.title("🌿 CarbonOptimaAI")
    st.caption(
        "Autonomous multi-agent carbon-aware energy optimization · "
        "UAE hourly grid intensity · counterfactual baseline with bootstrap CI"
    )

    render_sidebar()
    scenarios = load_scenarios()

    tabs = st.tabs([
        "📊 Live state",
        "🚨 Anomalies",
        "📈 Scenarios",
        "💬 Advisor",
    ])
    with tabs[0]:
        tab_live(scenarios)
    with tabs[1]:
        tab_anomalies()
    with tabs[2]:
        tab_scenarios(scenarios)
    with tabs[3]:
        tab_advisor(scenarios)


if __name__ == "__main__":
    main()
