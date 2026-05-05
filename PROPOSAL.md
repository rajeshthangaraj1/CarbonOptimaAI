# CarbonOptimaAI — Final Proposal

**Hackathon:** DEWA CleanTech Hackathon 2026
**Track (primary):** AI & Digitalisation
**Track (secondary):** Decarbonisation & Sustainability
**Title:** Autonomous Multi-Agent AI for Carbon-Aware Energy Optimization in the UAE

---

## 1. Problem

The UAE is pushing hard toward Net Zero 2050, but three gaps remain in current utility-side monitoring:

1. Energy data is rarely translated into **time-varying carbon impact** — most dashboards still use a flat emission factor.
2. Cooling drives 60–70% of summer peak load, yet there is no widely deployed system that **pre-cools using forecasted weather + grid carbon intensity**.
3. Operators see anomalies but get no **autonomous, simulated action plan** with a defensible counterfactual.

We close these three gaps.

---

## 2. Solution (one sentence)

A multi-agent decision system that ingests UAE consumption + weather + a **time-varying grid carbon intensity model**, detects cooling-driven emission peaks, and autonomously simulates load-shifting and pre-cooling actions — with a counterfactual baseline so the carbon savings are defensible, not hand-waved.

---

## 3. Why this wins (differentiation)

| Most submissions will do | We do |
|---|---|
| Flat 0.4 kg CO₂/kWh factor | Hourly UAE grid intensity (gas + solar + Barakah nuclear mix) |
| US datasets (PJM etc.) | UAE open data (bayanat.ae) + Open-Meteo Dubai weather |
| Generic "energy savings %" | Counterfactual baseline with confidence band |
| LLM wrapper called "multi-agent" | Real optimizer at the core; LLM only narrates |
| Slide-only impact | Live on-stage trigger demo (carbon spike → action fires) |

Selected wow-factor enhancements: **A** (time-varying intensity), **C** (cooling-specific agent), **D** (UAE open data), **F** (live demo trigger).

---

## 4. Architecture

```
 UAE Consumption (bayanat.ae)     Dubai Weather (Open-Meteo)
              │                           │
              └────────────┬──────────────┘
                           ▼
                    Energy Agent
                           ▼
            Grid Carbon Intensity Model  ◄── solar curve + gas baseload + Barakah
                           ▼
                    Carbon Agent
                           ▼
             ┌─────────────┴─────────────┐
             ▼                           ▼
      Pattern Agent                Cooling Agent
      (Isolation Forest)           (thermal-lag pre-cool)
             └─────────────┬─────────────┘
                           ▼
                    Strategy Agent
                  (candidate actions)
                           ▼
                  Orchestration Agent
                  (optimizer picks set)
                           ▼
                    Impact Agent
                (counterfactual baseline)
                           ▼
                  GenAI Advisor (LLM)
                           ▼
                  Streamlit Dashboard
```

---

## 5. Agents

| Agent | Job | Method |
|---|---|---|
| **Energy** | Clean, resample, feature-extract consumption | pandas |
| **Carbon** | kWh → kg CO₂ using **hourly** intensity | grid-mix model |
| **Pattern** | Anomalies + peak emission windows | Isolation Forest |
| **Cooling** | Pre-cool recommendation given temp forecast + thermal inertia | rule + lag model |
| **Strategy** | Generate 3–5 candidate actions per peak | rules + heuristics |
| **Orchestration** | Pick best action set under comfort constraints | greedy / linear program |
| **Impact** | Counterfactual: optimized vs. do-nothing | bootstrap CI |
| **GenAI Advisor** | Narrate *why* this plan was chosen (uses real numbers) | Claude API |

The Orchestration Agent is the **innovation core** — it gives a real reason for the multi-agent split (each agent owns a different objective and time horizon).

---

## 6. Data

| Source | Use | Fallback |
|---|---|---|
| **bayanat.ae** | UAE electricity consumption | Synthetic UAE-shaped profile derived from public averages |
| **Open-Meteo API** | Dubai hourly temp, humidity, irradiance | None needed (free, no key) |
| **Grid mix model** | Hourly carbon intensity | Built from public DEWA / IRENA mix figures |

We will **not** use PJM data. UAE-only.

---

## 7. Tech Stack

- Python 3.11
- pandas, numpy, scikit-learn (Isolation Forest)
- scipy / pulp (orchestration optimizer)
- Open-Meteo HTTP client
- Streamlit (dashboard)
- Anthropic Claude API (GenAI advisor)
- Plotly (timeline, before/after)

No heavyweight infra. Runs on a laptop. Demo-ready.

---

## 8. Build Plan (3 days)

### Day 1 — Data foundation + core agents (~10 hrs)
- [ ] Pull bayanat.ae datasets; build UAE-shaped fallback profile if needed
- [ ] Open-Meteo fetcher for Dubai (12 months, hourly)
- [ ] Hourly grid carbon intensity model
- [ ] EnergyAgent, CarbonAgent, PatternAgent

### Day 2 — Decision layer + cooling (~10 hrs)
- [ ] CoolingAgent (thermal-lag pre-cool logic)
- [ ] StrategyAgent (candidate action generator)
- [ ] OrchestrationAgent (optimizer)
- [ ] ImpactAgent with counterfactual + confidence band

### Day 3 — Interface + demo polish (~8 hrs)
- [ ] Streamlit dashboard: live intensity gauge, timeline, before/after, execute button
- [ ] GenAI Advisor wired to Claude API
- [ ] **Live trigger demo**: simulate grid carbon spike → orchestrator fires pre-cool + load shift on stage
- [ ] 3-min demo script, 3 slides (architecture / impact / UAE relevance)

---

## 9. Demo Flow (3 minutes)

1. **0:00** — Dashboard shows live UAE consumption + hourly carbon intensity
2. **0:30** — Pattern Agent flags an upcoming cooling-driven emission peak
3. **1:00** — Strategy Agent shows 4 candidate actions; Orchestrator picks the optimal 2
4. **1:30** — Click **Execute Scenario** → timeline animates pre-cool + load shift
5. **2:00** — Impact Agent shows counterfactual: kg CO₂ saved with confidence band
6. **2:30** — GenAI Advisor narrates the decision in plain English
7. **2:50** — UAE Net Zero 2050 alignment slide; close

---

## 10. Expected Impact (defensible numbers)

- **Peak demand:** 8–15% reduction (cooling pre-shift, conservative)
- **Carbon emissions:** 12–20% reduction in targeted windows
- **Methodology:** counterfactual baseline with 95% CI — no hand-waved percentages

Numbers are simulated but tied to a real optimization run, not a slide claim.

---

## 11. UAE Alignment

- **UAE Net Zero 2050** — directly supports demand-side decarbonisation
- **DEWA Smart Grid** — slots into existing AMI / SCADA telemetry
- **Mohammed bin Rashid Solar Park** — solar generation curve drives the intensity model
- **Cooling demand** — the dominant UAE energy challenge, addressed head-on

---

## 12. Open Questions (need decisions before coding)

1. **Data:** Try live bayanat.ae fetch first, or start with the UAE-shaped synthetic fallback and swap later? *(Recommendation: start synthetic, swap if bayanat is fetchable.)*
2. **LLM:** Claude API (best, needs key) or local Ollama (free, weaker)? *(Recommendation: Claude API — it's the GenAI Advisor; quality matters on stage.)*
3. **Scope:** Single-building view, or district-level (multiple buildings)? *(Recommendation: single-building for v1, district as stretch goal if Day 3 has slack.)*

---

## 13. Team Roles (fill in)

| Role | Owner |
|---|---|
| Data + agents (Day 1) | _TBD_ |
| Optimizer + cooling (Day 2) | _TBD_ |
| Streamlit + GenAI advisor (Day 3) | _TBD_ |
| Demo script + slides | _TBD_ |
| Pitch lead | _TBD_ |

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| bayanat.ae data unavailable / requires login | Synthetic UAE-shaped fallback profile, documented |
| Optimizer too slow for live demo | Pre-compute scenarios; "execute" plays a cached run |
| Claude API rate limit on stage | Cache the advisor narration for the demo path |
| Judges challenge "simulated" impact | Counterfactual baseline + CI is the answer |

---

**Status:** Awaiting answers to the three open questions in §12, then we start Day 1.
