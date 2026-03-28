"""
Scoring Models
--------------
Composite scores for every node in the graph.

Five scores, each 0–1 (higher = worse / more exposed):

  nnm_score               No Next Move — overall collapse fragility
  hidden_constraint_score Hidden assumption load / invisible dependency
  false_redundancy_score  Apparent redundancy that collapses to one path
  pressure_absorption_score How well stress redistributes (inverted: 1=poor)
  reversion_potential_score Value transfer opportunity if node fails
"""
from __future__ import annotations

import math
from typing import Optional

from app.models.graph import Graph, CollapseRisk
from app.engines.dependency import DependencyEngine
from app.engines.flow import FlowEngine
from app.engines.scenario import ScenarioEngine


# ---------------------------------------------------------------------------
# Weight config — tune without code changes
# ---------------------------------------------------------------------------

NNM_WEIGHTS = {
    "reroute_failure":        0.35,   # 1 - reroute_score
    "time_to_failure":        0.20,   # inverse normalised TTF
    "dependency_concentration": 0.20, # in-degree normalised by graph size
    "return_loop_absence":    0.15,   # flow broken-loop contribution
    "hidden_constraint":      0.10,   # hidden chokepoint delta
}


class ScoringEngine:
    """Computes all five scores for every node in the graph."""

    def __init__(self, graph: Graph):
        self.model = graph
        self.dep = DependencyEngine(graph)
        self.flow = FlowEngine(graph)
        self.scenario = ScenarioEngine(graph)
        self._flow_severity = self.flow.per_node_flow_severity()
        self._max_ttf: float = max(
            (n.attributes.time_sensitivity for n in graph.nodes if n.attributes.time_sensitivity > 0),
            default=1.0,
        )
        self._n_nodes = max(len(graph.nodes), 1)

    # ------------------------------------------------------------------
    # Individual scores
    # ------------------------------------------------------------------

    def reroute_failure_score(self, node_id: str) -> float:
        """1 - fraction of dependents still reachable after removal."""
        return 1.0 - self.dep.reroute_availability(node_id)

    def time_to_failure_score(self, node_id: str) -> float:
        """
        Normalised urgency: high score = fails quickly under pressure.
        """
        node = next((n for n in self.model.nodes if n.id == node_id), None)
        if not node:
            return 0.0
        ts = node.attributes.time_sensitivity
        load = node.attributes.load
        # High time-sensitivity + high load → high score
        return min(1.0, ts * (0.5 + load * 0.5))

    def dependency_concentration_score(self, node_id: str) -> float:
        """
        How concentrated is dependency on this node?
        (in-degree + out-degree) / 2*n_nodes
        """
        G = self.dep.G
        if node_id not in G:
            return 0.0
        in_deg = G.in_degree(node_id)
        out_deg = G.out_degree(node_id)
        return min(1.0, (in_deg + out_deg) / (2 * self._n_nodes))

    def return_loop_absence_score(self, node_id: str) -> float:
        """Flow severity component (broken loops + dead ends touching this node)."""
        return self._flow_severity.get(node_id, 0.0)

    def hidden_constraint_score(self, node_id: str) -> float:
        """Delta between conditional and baseline centrality."""
        return self.dep.hidden_chokepoint_score(node_id)

    def false_redundancy_score(self, node_id: str) -> float:
        return self.dep.false_redundancy_score(node_id)

    def pressure_absorption_score(self, node_id: str) -> float:
        """Inverted: high score = poor pressure absorption."""
        return 1.0 - self.dep.pressure_absorption_score(node_id)

    def reversion_potential_score(self, node_id: str) -> float:
        """
        Are there identifiable reversion targets?
        High score = clear beneficiaries exist (informative for positioning).
        """
        targets = self.dep.reversion_targets(node_id)
        return min(1.0, len(targets) / 3.0)

    # ------------------------------------------------------------------
    # Composite NNM score
    # ------------------------------------------------------------------

    def nnm_score(self, node_id: str) -> float:
        """
        Weighted composite No Next Move score.
        """
        components = {
            "reroute_failure":          self.reroute_failure_score(node_id),
            "time_to_failure":          self.time_to_failure_score(node_id),
            "dependency_concentration": self.dependency_concentration_score(node_id),
            "return_loop_absence":      self.return_loop_absence_score(node_id),
            "hidden_constraint":        self.hidden_constraint_score(node_id),
        }
        return sum(NNM_WEIGHTS[k] * v for k, v in components.items())

    # ------------------------------------------------------------------
    # Collapse risk category
    # ------------------------------------------------------------------

    def collapse_risk(self, nnm: float) -> CollapseRisk:
        if nnm >= 0.75:
            return CollapseRisk.CRITICAL
        if nnm >= 0.55:
            return CollapseRisk.HIGH
        if nnm >= 0.35:
            return CollapseRisk.MEDIUM
        if nnm >= 0.15:
            return CollapseRisk.LOW
        return CollapseRisk.NONE

    # ------------------------------------------------------------------
    # Full score bundle for one node
    # ------------------------------------------------------------------

    def score_node(self, node_id: str) -> dict:
        nnm = self.nnm_score(node_id)
        return {
            "node_id": node_id,
            "nnm_score": round(nnm, 4),
            "hidden_constraint_score": round(self.hidden_constraint_score(node_id), 4),
            "false_redundancy_score": round(self.false_redundancy_score(node_id), 4),
            "pressure_absorption_score": round(self.pressure_absorption_score(node_id), 4),
            "reversion_potential_score": round(self.reversion_potential_score(node_id), 4),
            "collapse_risk": self.collapse_risk(nnm).value,
        }

    def score_all(self) -> dict[str, dict]:
        return {n.id: self.score_node(n.id) for n in self.model.nodes}
