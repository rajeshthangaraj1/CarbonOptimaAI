import pulp

from core import config


class OrchestrationAgent:
    """Picks at most one strategy per anomaly window to maximize total CO2
    saved, subject to a global comfort budget.

    Variables: x[w, k] in {0, 1} for window w, candidate k.
    Objective: maximize sum(kg_co2_saved[w,k] * x[w,k]).
    Constraints:
      - sum_k x[w,k] <= 1 for each window (one strategy per window)
      - sum_{w,k} comfort_cost[w,k] * x[w,k] <= comfort_budget
      - x[w,k] = 0 if kg_co2_saved[w,k] <= 0 (never pick negative-saving)

    Greedy fallback (used if CBC is unavailable or LP infeasible):
    rank candidates by kg_co2_saved / max(comfort_cost, 1e-3),
    take in order while budget remains, at most one per window.
    """

    def __init__(self, comfort_budget=None):
        self.comfort_budget = (
            comfort_budget if comfort_budget is not None
            else config.get("orchestration.comfort_budget")
        )

    def optimize(self, candidates_by_window):
        """candidates_by_window: list[list[candidate dict]]. Returns list of
        (window_idx, candidate_idx, candidate_dict) for chosen strategies."""
        if not candidates_by_window:
            return []
        try:
            return self._solve_lp(candidates_by_window)
        except Exception:
            return self._greedy(candidates_by_window)

    def _solve_lp(self, cbw):
        prob = pulp.LpProblem("orchestrate", pulp.LpMaximize)
        x = {}
        for w, cand_list in enumerate(cbw):
            for k, cand in enumerate(cand_list):
                ub = 0 if cand["kg_co2_saved"] <= 0 else 1
                x[(w, k)] = pulp.LpVariable(
                    f"x_{w}_{k}", lowBound=0, upBound=ub, cat="Binary",
                )

        prob += pulp.lpSum(
            cand["kg_co2_saved"] * x[(w, k)]
            for w, cand_list in enumerate(cbw)
            for k, cand in enumerate(cand_list)
        )

        for w, cand_list in enumerate(cbw):
            prob += pulp.lpSum(x[(w, k)] for k in range(len(cand_list))) <= 1

        prob += pulp.lpSum(
            cand["comfort_cost"] * x[(w, k)]
            for w, cand_list in enumerate(cbw)
            for k, cand in enumerate(cand_list)
        ) <= self.comfort_budget

        prob.solve(pulp.PULP_CBC_CMD(msg=False))

        chosen = []
        for w, cand_list in enumerate(cbw):
            for k, cand in enumerate(cand_list):
                if pulp.value(x[(w, k)]) and pulp.value(x[(w, k)]) > 0.5:
                    chosen.append((w, k, cand))
        return chosen

    def _greedy(self, cbw):
        flat = []
        for w, cand_list in enumerate(cbw):
            for k, cand in enumerate(cand_list):
                if cand["kg_co2_saved"] <= 0:
                    continue
                ratio = cand["kg_co2_saved"] / max(cand["comfort_cost"], 1e-3)
                flat.append((ratio, w, k, cand))
        flat.sort(reverse=True)

        chosen = []
        used_windows = set()
        budget = self.comfort_budget
        for _, w, k, cand in flat:
            if w in used_windows:
                continue
            if cand["comfort_cost"] > budget:
                continue
            chosen.append((w, k, cand))
            used_windows.add(w)
            budget -= cand["comfort_cost"]
        return chosen
