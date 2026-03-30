"""
Adversarial Scenario Engine
----------------------------
Systematically generates the scenarios most likely to be missed by
conventional analysis — the surprises, the compound failures, the
scenarios that route around current mitigations.

Instead of waiting for novel situations to arrive, this engine
exhausts the space of dangerous surprises before they happen.

Scenario categories:
  MAX_DAMAGE       — find the k-node combination that causes maximum cascade
  SURPRISE_FAILURE — nodes that seem stable but are one hop from critical
  COMPOUND_FAILURE — 2-3 node combinations with disproportionate joint damage
  MITIGATION_DEFEAT — scenarios that route around current Fix recommendations
  SILENT_DRIFT     — slow degradation paths that evade threshold monitoring
  DEPENDENCY_INVERSION — scenarios where assumed flow directions reverse
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import networkx as nx

from app.models.graph import Graph, GraphAnalysis, ActionLabel
from app.engines.dependency import DependencyEngine
from app.engines.scoring import ScoringEngine


class ScenarioCategory(str, Enum):
    MAX_DAMAGE        = "max_damage"
    SURPRISE_FAILURE  = "surprise_failure"
    COMPOUND_FAILURE  = "compound_failure"
    MITIGATION_DEFEAT = "mitigation_defeat"
    SILENT_DRIFT      = "silent_drift"


@dataclass
class AdversarialScenario:
    category: ScenarioCategory
    trigger_nodes: list[str]        # nodes that fail/are stressed
    trigger_labels: list[str]
    cascade_depth: int              # how deep the cascade goes
    affected_nodes: list[str]       # all nodes impacted
    affected_labels: list[str]
    why_dangerous: str              # plain-English explanation
    why_missed: str                 # why conventional analysis would miss this
    damage_score: float             # 0–1 composite severity
    defeat_vector: Optional[str]    # if MITIGATION_DEFEAT, what it bypasses


@dataclass
class AdversarialReport:
    scenarios: list[AdversarialScenario]
    worst_scenario: AdversarialScenario
    total_scenarios_generated: int
    most_dangerous_node: str
    most_dangerous_label: str
    surprise_nodes: list[str]       # nodes that appear safe but aren't
    surprise_labels: list[str]
    narrative: str


class AdversarialEngine:
    """
    Generates maximally dangerous, maximally surprising scenarios.
    """

    def __init__(self, graph: Graph, analysis: Optional[GraphAnalysis] = None):
        self.graph = graph
        self.analysis = analysis
        self.dep = DependencyEngine(graph)
        self.scoring = ScoringEngine(graph)
        self.G = self.dep.G
        self._node_map = {n.id: n for n in graph.nodes}
        self._label_map = {n.id: n.label for n in graph.nodes}

    def _cascade_size(self, removed_nodes: list[str]) -> tuple[int, list[str]]:
        """Compute cascade depth when a set of nodes are removed."""
        G2 = self.G.copy()
        G2.remove_nodes_from([n for n in removed_nodes if n in G2])
        if len(G2.nodes) == 0:
            return 0, []
        # Nodes that become unreachable from any source
        sources = [n for n in G2.nodes if G2.in_degree(n) == 0]
        reachable = set()
        for s in sources:
            reachable.update(nx.descendants(G2, s))
            reachable.add(s)
        unreachable = [n for n in self.G.nodes if n not in reachable and n not in removed_nodes]
        return len(unreachable), unreachable

    def generate_max_damage(self, top_k: int = 5) -> list[AdversarialScenario]:
        """Find single nodes whose removal causes maximum cascade damage."""
        scenarios = []
        damage_scores = []
        for node in self.graph.nodes:
            cascade_size, affected = self._cascade_size([node.id])
            score = self.scoring.nnm_score(node.id)
            # A node with LOW NNM score but HIGH cascade is the dangerous surprise
            damage = cascade_size / max(len(self.graph.nodes) - 1, 1)
            damage_scores.append((node.id, damage, cascade_size, affected, score))

        damage_scores.sort(key=lambda x: -x[1])

        for nid, damage, cascade_size, affected, nnm_score in damage_scores[:top_k]:
            label = self._label_map[nid]
            affected_labels = [self._label_map.get(n, n) for n in affected[:10]]
            scenarios.append(AdversarialScenario(
                category=ScenarioCategory.MAX_DAMAGE,
                trigger_nodes=[nid],
                trigger_labels=[label],
                cascade_depth=cascade_size,
                affected_nodes=affected[:10],
                affected_labels=affected_labels,
                why_dangerous=f"Failure of '{label}' renders {cascade_size} downstream node(s) inoperable.",
                why_missed="Max-damage analysis identifies structural leverage, not just obvious SPOFs.",
                damage_score=round(damage, 4),
                defeat_vector=None,
            ))
        return scenarios

    def generate_surprise_failures(self) -> list[AdversarialScenario]:
        """
        Find nodes that appear safe (low NNM score) but are adjacent to
        critical failures — the 'one hop from catastrophe' problem.
        """
        scenarios = []
        for node in self.graph.nodes:
            nid = node.id
            own_score = self.scoring.nnm_score(nid)
            if own_score > 0.40:
                continue  # not surprising — already flagged as risky

            # Check immediate neighbors
            neighbors = list(self.G.successors(nid))
            critical_neighbors = [
                n for n in neighbors
                if self.scoring.nnm_score(n) > 0.50
            ]
            if not critical_neighbors:
                continue

            # This seemingly-safe node is feeding into critical nodes
            cn_labels = [self._label_map.get(n, n) for n in critical_neighbors[:3]]
            cascade_size, affected = self._cascade_size([nid])

            scenarios.append(AdversarialScenario(
                category=ScenarioCategory.SURPRISE_FAILURE,
                trigger_nodes=[nid],
                trigger_labels=[node.label],
                cascade_depth=cascade_size,
                affected_nodes=affected[:8],
                affected_labels=[self._label_map.get(n, n) for n in affected[:8]],
                why_dangerous=f"'{node.label}' has low NNM score ({own_score:.2f}) but directly feeds critical node(s): {', '.join(cn_labels)}.",
                why_missed="Low individual risk score masks critical position in failure chain.",
                damage_score=round(0.3 + len(critical_neighbors) * 0.15 + own_score, 4),
                defeat_vector=None,
            ))
        scenarios.sort(key=lambda s: -s.damage_score)
        return scenarios[:5]

    def generate_compound_failures(self, max_pairs: int = 30) -> list[AdversarialScenario]:
        """
        Find 2-node combinations that cause disproportionate joint damage
        compared to their individual damage scores.
        """
        scenarios = []
        nodes = list(self.graph.nodes)
        if len(nodes) < 2:
            return []

        # Score individuals first
        individual_scores = {n.id: self._cascade_size([n.id])[0] for n in nodes}

        # Check pairs
        pairs = list(itertools.combinations(nodes, 2))
        if len(pairs) > max_pairs:
            # Prioritize pairs with high individual scores
            pairs = sorted(pairs, key=lambda p: -(individual_scores[p[0].id] + individual_scores[p[1].id]))[:max_pairs]

        for n1, n2 in pairs:
            joint_cascade, affected = self._cascade_size([n1.id, n2.id])
            individual_sum = individual_scores[n1.id] + individual_scores[n2.id]
            # Synergy: joint > sum of individuals
            synergy = joint_cascade - individual_sum
            if synergy < 2:
                continue  # no meaningful interaction effect

            labels = [n1.label, n2.label]
            scenarios.append(AdversarialScenario(
                category=ScenarioCategory.COMPOUND_FAILURE,
                trigger_nodes=[n1.id, n2.id],
                trigger_labels=labels,
                cascade_depth=joint_cascade,
                affected_nodes=affected[:10],
                affected_labels=[self._label_map.get(n, n) for n in affected[:10]],
                why_dangerous=f"Joint failure of '{n1.label}' + '{n2.label}' cascades to {joint_cascade} nodes — {synergy} more than their individual effects combined.",
                why_missed="Single-node analysis misses interaction effects between seemingly independent failures.",
                damage_score=round(min(1.0, joint_cascade / max(len(nodes) - 2, 1)), 4),
                defeat_vector=None,
            ))

        scenarios.sort(key=lambda s: -s.cascade_depth)
        return scenarios[:5]

    def generate_mitigation_defeats(self) -> list[AdversarialScenario]:
        """
        Find scenarios that route around current Fix recommendations —
        the fixes that leave the system still vulnerable.
        """
        if not self.analysis:
            return []

        scenarios = []
        # Nodes recommended for Fix
        fix_nodes = {
            cp.node_id for cp in self.analysis.collapse_points
            if cp.action == ActionLabel.FIX
        }

        if not fix_nodes:
            return []

        # If all Fix nodes are "fixed" (removed from graph), what still fails?
        # Model the fixed state
        G_fixed = self.G.copy()
        # "Fixing" a node means it no longer fails — but its DEPENDENCIES still exist
        # The defeat: a path that doesn't go through any fix node but still causes cascade

        for node in self.graph.nodes:
            if node.id in fix_nodes:
                continue  # this is already being fixed
            cascade, affected = self._cascade_size([node.id])
            if cascade < 2:
                continue
            # Check if any affected nodes are critical (high NNM) and not in fix set
            critical_affected = [
                n for n in affected
                if n not in fix_nodes and self.scoring.nnm_score(n) > 0.4
            ]
            if not critical_affected:
                continue

            fix_labels = [self._label_map.get(n, n) for n in fix_nodes]
            scenarios.append(AdversarialScenario(
                category=ScenarioCategory.MITIGATION_DEFEAT,
                trigger_nodes=[node.id],
                trigger_labels=[node.label],
                cascade_depth=cascade,
                affected_nodes=affected[:8],
                affected_labels=[self._label_map.get(n, n) for n in affected[:8]],
                why_dangerous=f"'{node.label}' is NOT in the Fix list but causes cascade to {len(critical_affected)} critical node(s).",
                why_missed="Current mitigations focus on obvious SPOFs but miss this attack surface.",
                damage_score=round(min(1.0, cascade / max(len(self.graph.nodes) - 1, 1)), 4),
                defeat_vector=f"Bypasses Fix recommendations ({', '.join(fix_labels[:3])})",
            ))

        scenarios.sort(key=lambda s: -s.damage_score)
        return scenarios[:4]

    def generate_silent_drift(self) -> list[AdversarialScenario]:
        """
        Find slow degradation paths: chains of medium-stressed nodes
        where cumulative drift could reach threshold invisibly.
        """
        scenarios = []
        for node in self.graph.nodes:
            nid = node.id
            # Node with moderate but worsening metrics
            mid_load = 0.45 <= node.attributes.load <= 0.75
            mid_reliability = 0.45 <= node.attributes.criticality <= 0.75
            if not (mid_load or mid_reliability):
                continue

            # Look for chains of similarly-stressed successors
            path = [nid]
            current = nid
            for _ in range(5):
                successors = list(self.G.successors(current))
                if not successors:
                    break
                # Pick most stressed successor
                next_node = max(
                    successors,
                    key=lambda n: self._node_map[n].attributes.load if n in self._node_map else 0,
                )
                if next_node in path:
                    break
                nn = self._node_map.get(next_node)
                if nn and nn.attributes.load > 0.35:
                    path.append(next_node)
                    current = next_node
                else:
                    break

            if len(path) < 3:
                continue

            path_labels = [self._label_map.get(n, n) for n in path]
            scenarios.append(AdversarialScenario(
                category=ScenarioCategory.SILENT_DRIFT,
                trigger_nodes=path,
                trigger_labels=path_labels,
                cascade_depth=len(path),
                affected_nodes=path,
                affected_labels=path_labels,
                why_dangerous=f"Chain of {len(path)} nodes each operating at moderate stress: {' → '.join(path_labels[:4])}. Cumulative drift could cross threshold invisibly.",
                why_missed="Each node individually appears stable; combined trajectory is not.",
                damage_score=round(
                    min(1.0, sum(self._node_map[n].attributes.load for n in path if n in self._node_map) / (len(path) * 0.9)),
                    4
                ),
                defeat_vector=None,
            ))

        scenarios.sort(key=lambda s: -s.damage_score)
        return scenarios[:4]

    def run(self) -> AdversarialReport:
        """Generate all adversarial scenario categories and compile report."""
        all_scenarios = []
        all_scenarios.extend(self.generate_max_damage(top_k=4))
        all_scenarios.extend(self.generate_surprise_failures())
        all_scenarios.extend(self.generate_compound_failures(max_pairs=20))
        all_scenarios.extend(self.generate_mitigation_defeats())
        all_scenarios.extend(self.generate_silent_drift())

        if not all_scenarios:
            empty = AdversarialScenario(
                category=ScenarioCategory.MAX_DAMAGE, trigger_nodes=[], trigger_labels=[],
                cascade_depth=0, affected_nodes=[], affected_labels=[],
                why_dangerous="No adversarial scenarios detected.", why_missed="",
                damage_score=0.0, defeat_vector=None,
            )
            return AdversarialReport(
                scenarios=[], worst_scenario=empty, total_scenarios_generated=0,
                most_dangerous_node="", most_dangerous_label="",
                surprise_nodes=[], surprise_labels=[], narrative="No adversarial scenarios found.",
            )

        all_scenarios.sort(key=lambda s: -s.damage_score)
        worst = all_scenarios[0]

        surprise = [s for s in all_scenarios if s.category == ScenarioCategory.SURPRISE_FAILURE]
        surprise_nodes = [s.trigger_nodes[0] for s in surprise if s.trigger_nodes]
        surprise_labels = [s.trigger_labels[0] for s in surprise if s.trigger_labels]

        # Most dangerous single node across all scenarios
        node_danger: dict[str, float] = {}
        for s in all_scenarios:
            for nid in s.trigger_nodes:
                node_danger[nid] = max(node_danger.get(nid, 0), s.damage_score)
        most_dangerous = max(node_danger, key=node_danger.get) if node_danger else ""
        most_dangerous_label = self._label_map.get(most_dangerous, most_dangerous)

        narrative = self._build_narrative(all_scenarios, worst)

        return AdversarialReport(
            scenarios=all_scenarios,
            worst_scenario=worst,
            total_scenarios_generated=len(all_scenarios),
            most_dangerous_node=most_dangerous,
            most_dangerous_label=most_dangerous_label,
            surprise_nodes=surprise_nodes,
            surprise_labels=surprise_labels,
            narrative=narrative,
        )

    def _build_narrative(
        self, scenarios: list[AdversarialScenario], worst: AdversarialScenario
    ) -> str:
        defeats = [s for s in scenarios if s.category == ScenarioCategory.MITIGATION_DEFEAT]
        surprises = [s for s in scenarios if s.category == ScenarioCategory.SURPRISE_FAILURE]
        parts = [f"{len(scenarios)} adversarial scenarios generated."]
        parts.append(f"Worst case: {worst.why_dangerous}")
        if surprises:
            labels = ", ".join(f"'{s.trigger_labels[0]}'" for s in surprises[:2])
            parts.append(f"Surprise failures (appear safe, aren't): {labels}.")
        if defeats:
            parts.append(f"{len(defeats)} scenario(s) route around current Fix recommendations.")
        return " ".join(parts)
