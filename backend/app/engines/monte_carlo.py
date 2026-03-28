"""
Monte Carlo simulation engine.
Runs N probabilistic trials over the ScenarioEngine by perturbing node/edge
attributes within uncertainty bounds and returns statistical distributions of
outcome metrics.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.models.graph import Graph, Node, Edge
from app.engines.scenario import ScenarioEngine, ScenarioResult


@dataclass
class DistStats:
    mean: float
    median: float
    p5: float
    p95: float
    std: float


@dataclass
class MonteCarloResult:
    n_trials: int
    simulation_type: str
    node_id: str
    collapse_probability: float          # fraction of trials where is_reroutable == False
    reroute_score: DistStats
    cascade_depth: DistStats
    time_to_failure_hours: Optional[DistStats]
    histogram_reroute: list[dict]        # [{bin_start, bin_end, count}, ...]
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def ds(d: Optional[DistStats]) -> Optional[dict]:
            if d is None:
                return None
            return {"mean": d.mean, "median": d.median, "p5": d.p5, "p95": d.p95, "std": d.std}
        return {
            "n_trials": self.n_trials,
            "simulation_type": self.simulation_type,
            "node_id": self.node_id,
            "collapse_probability": self.collapse_probability,
            "reroute_score": ds(self.reroute_score),
            "cascade_depth": ds(self.cascade_depth),
            "time_to_failure_hours": ds(self.time_to_failure_hours),
            "histogram_reroute": self.histogram_reroute,
            "recommendations": self.recommendations,
        }


# Performance guard: skip expensive centrality in scoring for large graphs
_LARGE_GRAPH_THRESHOLD = 80


class MonteCarloEngine:
    """
    Perturbs graph attributes N times and runs the same simulation each trial.

    Perturbation model:
      reliability  — Beta(α, β) derived from edge reliability with effective n=10
      load         — clipped Normal(load, 0.10)
      criticality  — clipped Uniform(v - 0.10, v + 0.10)
      replaceability — clipped Uniform(v - 0.10, v + 0.10)
      latency      — clipped Normal(latency, latency * 0.20)
    """

    def __init__(self, graph: Graph, n_trials: int = 500, seed: Optional[int] = None):
        self.graph = graph
        self.n_trials = max(1, min(n_trials, 2000))
        self.rng = np.random.default_rng(seed)
        self._large = len(graph.nodes) > _LARGE_GRAPH_THRESHOLD

    # ------------------------------------------------------------------
    # Perturbation
    # ------------------------------------------------------------------

    def _perturb_graph(self) -> Graph:
        """Return a deep-copied Graph with attributes jittered by the rng."""
        g = copy.deepcopy(self.graph)

        for node in g.nodes:
            a = node.attributes
            a.load = float(np.clip(self.rng.normal(a.load, 0.10), 0.0, 1.0))
            a.criticality = float(np.clip(self.rng.uniform(a.criticality - 0.10, a.criticality + 0.10), 0.0, 1.0))
            a.replaceability = float(np.clip(self.rng.uniform(a.replaceability - 0.10, a.replaceability + 0.10), 0.0, 1.0))

        for edge in g.edges:
            a = edge.attributes
            # Beta perturbation for reliability
            r = a.reliability
            eff_n = 10.0
            alpha = r * eff_n + 1e-6
            beta = (1 - r) * eff_n + 1e-6
            a.reliability = float(np.clip(self.rng.beta(alpha, beta), 0.0, 1.0))
            # Latency
            if a.latency > 0:
                a.latency = float(np.clip(self.rng.normal(a.latency, a.latency * 0.20), 0.0, a.latency * 5))

        return g

    # ------------------------------------------------------------------
    # Single-trial runner
    # ------------------------------------------------------------------

    def _run_trial(self, sim_type: str, node_id: str, params: dict) -> Optional[ScenarioResult]:
        g = self._perturb_graph()
        engine = ScenarioEngine(g)

        dispatch = {
            "node_removal":       lambda: engine.node_removal(node_id),
            "delay_injection":    lambda: engine.delay_injection(node_id, params.get("multiplier", 5.0)),
            "cost_shock":         lambda: engine.cost_shock(node_id, params.get("reduction", 0.5)),
            "assumption_failure": lambda: engine.assumption_failure(node_id),
            "approval_blockage":  lambda: engine.approval_blockage(node_id),
            "vendor_outage":      lambda: engine.vendor_outage(node_id),
            "clause_invalidation":lambda: engine.clause_invalidation(node_id),
            "leadership_absence": lambda: engine.leadership_absence(node_id),
        }
        fn = dispatch.get(sim_type)
        if fn is None:
            return None
        return fn()

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self, simulation_type: str, node_id: str, params: dict = {}) -> MonteCarloResult:
        reroutes: list[float] = []
        cascades: list[float] = []
        ttfs: list[float] = []
        n_blocked = 0

        for _ in range(self.n_trials):
            result = self._run_trial(simulation_type, node_id, params)
            if result is None:
                continue
            reroutes.append(result.reroute_score)
            cascades.append(float(result.cascade_depth))
            if result.time_to_failure_hours is not None:
                ttfs.append(result.time_to_failure_hours)
            if not result.is_reroutable:
                n_blocked += 1

        if not reroutes:
            # No valid trials
            empty = DistStats(0, 0, 0, 0, 0)
            return MonteCarloResult(
                n_trials=0, simulation_type=simulation_type, node_id=node_id,
                collapse_probability=1.0, reroute_score=empty, cascade_depth=empty,
                time_to_failure_hours=None, histogram_reroute=[],
                recommendations=["No valid trials completed — check node_id and simulation_type."],
            )

        arr_r = np.array(reroutes)
        arr_c = np.array(cascades)
        collapse_prob = n_blocked / len(reroutes)

        def stats(arr: np.ndarray) -> DistStats:
            return DistStats(
                mean=round(float(arr.mean()), 4),
                median=round(float(np.median(arr)), 4),
                p5=round(float(np.percentile(arr, 5)), 4),
                p95=round(float(np.percentile(arr, 95)), 4),
                std=round(float(arr.std()), 4),
            )

        # Histogram (10 bins, 0-1 range for reroute score)
        counts, edges = np.histogram(arr_r, bins=10, range=(0.0, 1.0))
        histogram = [
            {"bin_start": round(float(edges[i]), 2), "bin_end": round(float(edges[i + 1]), 2), "count": int(counts[i])}
            for i in range(len(counts))
        ]

        # Recommendations
        recs = []
        if collapse_prob > 0.5:
            recs.append(f"Collapse probability is {collapse_prob:.0%} — treat as no-reroute scenario.")
        elif collapse_prob > 0.2:
            recs.append(f"Collapse probability is {collapse_prob:.0%} — significant downside tail risk.")
        else:
            recs.append(f"System is likely reroutable ({(1-collapse_prob):.0%} of trials), but monitor p95 cascade depth.")
        if arr_r.std() > 0.25:
            recs.append("High variance in reroute outcomes — results are sensitive to input uncertainty. Improve data confidence.")

        return MonteCarloResult(
            n_trials=len(reroutes),
            simulation_type=simulation_type,
            node_id=node_id,
            collapse_probability=round(collapse_prob, 4),
            reroute_score=stats(arr_r),
            cascade_depth=stats(arr_c),
            time_to_failure_hours=stats(np.array(ttfs)) if ttfs else None,
            histogram_reroute=histogram,
            recommendations=recs,
        )
