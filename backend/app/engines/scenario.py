"""
Scenario Engine
---------------
Runs lawful simulations against a graph to find the point of no reroute.

Simulation types:
  - node_removal        : remove a node and measure downstream cascade
  - delay_injection     : increase latency on all edges from a node
  - cost_shock          : reduce reliability on all edges from a node
  - assumption_failure  : set an assumption node's replaceability to 0
  - approval_blockage   : remove all APPROVES / GOVERNED_BY edges from a node
  - vendor_outage       : remove all edges touching a VENDOR node
  - clause_invalidation : remove all edges from a CONTRACT_CLAUSE node
  - leadership_absence  : remove a PERSON node with high criticality
  - comms_blackout      : remove all INFORMS edges from a set of nodes

Each simulation returns a ScenarioResult with:
  - affected nodes
  - reroute_score (0 = no reroute, 1 = full reroute)
  - cascade depth
  - time_to_failure estimate (heuristic)
  - recommendations
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from app.models.graph import Graph, NodeType, EdgeType


@dataclass
class ScenarioResult:
    simulation_type: str
    target_node_ids: list[str]
    target_labels: list[str]
    affected_nodes: list[str]
    reroute_score: float       # 0=blocked, 1=fully reroutable
    cascade_depth: int
    time_to_failure_hours: Optional[float]
    pressure_redistribution: float   # 0=localises, 1=distributes
    is_reroutable: bool
    description: str
    recommendations: list[str] = field(default_factory=list)


class ScenarioEngine:
    """Runs deterministic scenario simulations."""

    def __init__(self, graph: Graph):
        self.model = graph
        self._nodes_by_id = {n.id: n for n in graph.nodes}
        self.G = self._build_nx()

    def _build_nx(self) -> nx.DiGraph:
        G = nx.DiGraph()
        for node in self.model.nodes:
            G.add_node(
                node.id,
                label=node.label,
                node_type=node.node_type.value,
                criticality=node.attributes.criticality,
                replaceability=node.attributes.replaceability,
                reversibility=node.attributes.reversibility,
                time_sensitivity=node.attributes.time_sensitivity,
                load=node.attributes.load,
            )
        for edge in self.model.edges:
            G.add_edge(
                edge.source, edge.target,
                edge_type=edge.edge_type.value,
                weight=edge.attributes.weight,
                reliability=edge.attributes.reliability,
                latency=edge.attributes.latency,
            )
        return G

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reroute_score(self, G_modified: nx.DiGraph, removed_nodes: set[str]) -> float:
        """Fraction of originally-dependent nodes still able to reach an original sink."""
        dependents = set()
        for rn in removed_nodes:
            if rn in self.G:
                dependents.update(self.G.predecessors(rn))
        dependents -= removed_nodes

        if not dependents:
            return 1.0

        # Use original graph's sinks as targets (not the modified graph's sinks,
        # which may include dependents that lost their outgoing edges).
        original_sinks = [
            n for n in self.G.nodes
            if self.G.out_degree(n) == 0 and n not in removed_nodes
        ]
        if not original_sinks:
            return 0.0

        reachable = sum(
            1 for d in dependents
            if d in G_modified and any(
                s in G_modified and nx.has_path(G_modified, d, s)
                for s in original_sinks
            )
        )
        return reachable / len(dependents)

    def _cascade_depth(self, G_modified: nx.DiGraph, removed_nodes: set[str]) -> int:
        """Max BFS depth of nodes reachable from removed nodes in the original graph."""
        depths = []
        for rn in removed_nodes:
            if rn in self.G:
                desc = list(nx.descendants(self.G, rn))
                if desc:
                    lengths = nx.single_source_shortest_path_length(self.G, rn)
                    depths.append(max(lengths.values()))
        return max(depths) if depths else 0

    def _pressure_redistribution(self, removed_nodes: set[str]) -> float:
        """0=pressure localises, 1=distributes well."""
        G_minus = self.G.copy()
        G_minus.remove_nodes_from(removed_nodes)
        if G_minus.number_of_nodes() == 0:
            return 0.0
        # Measure whether remaining nodes have multiple paths
        in_degrees = [G_minus.in_degree(n) for n in G_minus.nodes]
        avg_in = sum(in_degrees) / len(in_degrees)
        return min(1.0, avg_in / 3.0)  # 3+ incoming paths → good redistribution

    def _time_to_failure(self, node_id: str) -> Optional[float]:
        """Heuristic: based on time_sensitivity and load."""
        n = self._nodes_by_id.get(node_id)
        if not n:
            return None
        ts = n.attributes.time_sensitivity
        load = n.attributes.load
        # High sensitivity + high load → faster failure
        if ts < 0.01:
            return None  # not time sensitive
        base_hours = 168.0  # one week
        return base_hours * (1 - ts) * (1 - load * 0.5)

    def _make_result(
        self,
        sim_type: str,
        targets: list[str],
        G_mod: nx.DiGraph,
        removed: set[str],
        description: str,
        recs: list[str],
    ) -> ScenarioResult:
        labels = [self.G.nodes[t].get("label", t) for t in targets if t in self.G]
        affected = []
        for t in targets:
            if t in self.G:
                affected.extend(nx.descendants(self.G, t))
        affected = list(set(affected) - removed)

        rs = self._reroute_score(G_mod, removed)
        return ScenarioResult(
            simulation_type=sim_type,
            target_node_ids=targets,
            target_labels=labels,
            affected_nodes=affected,
            reroute_score=rs,
            cascade_depth=self._cascade_depth(G_mod, removed),
            time_to_failure_hours=self._time_to_failure(targets[0]) if targets else None,
            pressure_redistribution=self._pressure_redistribution(removed),
            is_reroutable=rs > 0.5,
            description=description,
            recommendations=recs,
        )

    # ------------------------------------------------------------------
    # Simulation types
    # ------------------------------------------------------------------

    def node_removal(self, node_id: str) -> ScenarioResult:
        G_mod = self.G.copy()
        if node_id in G_mod:
            G_mod.remove_node(node_id)
        label = self.G.nodes[node_id].get("label", node_id) if node_id in self.G else node_id
        return self._make_result(
            "node_removal", [node_id], G_mod, {node_id},
            f"Remove '{label}' completely from the graph.",
            ["Check for substitute nodes", "Assess rebuild cost", "Identify upstream exposure"],
        )

    def delay_injection(self, node_id: str, delay_multiplier: float = 5.0) -> ScenarioResult:
        G_mod = self.G.copy()
        for u, v, data in self.G.out_edges(node_id, data=True):
            if G_mod.has_edge(u, v):
                G_mod[u][v]["latency"] = data.get("latency", 0) * delay_multiplier
        label = self.G.nodes[node_id].get("label", node_id) if node_id in self.G else node_id
        # Compute how many paths now exceed a 24h deadline
        affected = list(nx.descendants(self.G, node_id)) if node_id in self.G else []
        rs = 0.8  # delays are partial, not full removal
        return ScenarioResult(
            simulation_type="delay_injection",
            target_node_ids=[node_id],
            target_labels=[label],
            affected_nodes=affected,
            reroute_score=rs,
            cascade_depth=len(affected),
            time_to_failure_hours=self._time_to_failure(node_id),
            pressure_redistribution=0.4,
            is_reroutable=True,
            description=f"Inject {delay_multiplier}x latency on all outgoing edges of '{label}'.",
            recommendations=["Buffer time in downstream schedules", "Pre-approve parallel paths"],
        )

    def cost_shock(self, node_id: str, reliability_reduction: float = 0.5) -> ScenarioResult:
        G_mod = self.G.copy()
        for u, v in self.G.out_edges(node_id):
            if G_mod.has_edge(u, v):
                G_mod[u][v]["reliability"] = max(0.0, G_mod[u][v].get("reliability", 1.0) - reliability_reduction)
        label = self.G.nodes[node_id].get("label", node_id) if node_id in self.G else node_id
        rs = 1.0 - reliability_reduction
        return ScenarioResult(
            simulation_type="cost_shock",
            target_node_ids=[node_id],
            target_labels=[label],
            affected_nodes=list(nx.descendants(self.G, node_id)) if node_id in self.G else [],
            reroute_score=rs,
            cascade_depth=self._cascade_depth(G_mod, set()),
            time_to_failure_hours=None,
            pressure_redistribution=0.5,
            is_reroutable=rs > 0.4,
            description=f"Reduce reliability on all edges from '{label}' by {reliability_reduction:.0%}.",
            recommendations=["Hedge via alternative suppliers", "Renegotiate SLAs"],
        )

    def assumption_failure(self, node_id: str) -> ScenarioResult:
        """Set assumption node to irreplaceable."""
        label = self.G.nodes[node_id].get("label", node_id) if node_id in self.G else node_id
        G_mod = self.G.copy()
        if node_id in G_mod:
            G_mod.nodes[node_id]["replaceability"] = 0.0
        removed = {node_id}
        return self._make_result(
            "assumption_failure", [node_id], G_mod, removed,
            f"Mark assumption '{label}' as non-negotiable and non-replaceable.",
            ["Document assumption explicitly", "Validate with stakeholders", "Build contingency if assumption can break"],
        )

    def approval_blockage(self, node_id: str) -> ScenarioResult:
        """Remove all APPROVES and GOVERNED_BY edges from a node."""
        G_mod = self.G.copy()
        blocked_types = {EdgeType.APPROVES.value, EdgeType.GOVERNED_BY.value}
        edges_to_remove = [
            (u, v) for u, v, d in self.G.edges(node_id, data=True)
            if d.get("edge_type") in blocked_types
        ]
        G_mod.remove_edges_from(edges_to_remove)
        label = self.G.nodes[node_id].get("label", node_id) if node_id in self.G else node_id
        rs = self._reroute_score(G_mod, set())
        return ScenarioResult(
            simulation_type="approval_blockage",
            target_node_ids=[node_id],
            target_labels=[label],
            affected_nodes=[v for u, v in edges_to_remove],
            reroute_score=rs,
            cascade_depth=len(edges_to_remove),
            time_to_failure_hours=self._time_to_failure(node_id),
            pressure_redistribution=0.3,
            is_reroutable=rs > 0.5,
            description=f"Block all approval/governance edges from '{label}'.",
            recommendations=["Identify delegation authority", "Map escalation path", "Pre-sign where possible"],
        )

    def vendor_outage(self, vendor_node_id: str) -> ScenarioResult:
        G_mod = self.G.copy()
        removed = set()
        if vendor_node_id in G_mod:
            removed.add(vendor_node_id)
            G_mod.remove_node(vendor_node_id)
        label = self.G.nodes[vendor_node_id].get("label", vendor_node_id) if vendor_node_id in self.G else vendor_node_id
        return self._make_result(
            "vendor_outage", [vendor_node_id], G_mod, removed,
            f"Simulate full outage of vendor '{label}'.",
            ["Qualify backup vendors", "Review contract exit clauses", "Test fallback procedures"],
        )

    def clause_invalidation(self, clause_node_id: str) -> ScenarioResult:
        G_mod = self.G.copy()
        removed = set()
        if clause_node_id in G_mod:
            removed.add(clause_node_id)
            G_mod.remove_node(clause_node_id)
        label = self.G.nodes[clause_node_id].get("label", clause_node_id) if clause_node_id in self.G else clause_node_id
        return self._make_result(
            "clause_invalidation", [clause_node_id], G_mod, removed,
            f"Invalidate contract clause '{label}'.",
            ["Review governing law fallback", "Identify dependent obligations", "Prepare renegotiation position"],
        )

    def leadership_absence(self, person_node_id: str) -> ScenarioResult:
        return self.node_removal(person_node_id)

    def comms_blackout(self, node_ids: list[str]) -> ScenarioResult:
        G_mod = self.G.copy()
        informs_edges = [
            (u, v) for u, v, d in self.G.edges(data=True)
            if d.get("edge_type") == EdgeType.INFORMS.value and u in node_ids
        ]
        G_mod.remove_edges_from(informs_edges)
        labels = [self.G.nodes[n].get("label", n) for n in node_ids if n in self.G]
        affected = list({v for u, v in informs_edges})
        rs = self._reroute_score(G_mod, set())
        return ScenarioResult(
            simulation_type="comms_blackout",
            target_node_ids=node_ids,
            target_labels=labels,
            affected_nodes=affected,
            reroute_score=rs,
            cascade_depth=len(affected),
            time_to_failure_hours=None,
            pressure_redistribution=0.2,
            is_reroutable=rs > 0.5,
            description=f"Cut all INFORMS edges from {labels}.",
            recommendations=["Establish out-of-band communication", "Document information dependencies", "Create status dashboards"],
        )

    # ------------------------------------------------------------------
    # Run all scenarios for a single node
    # ------------------------------------------------------------------

    def full_node_simulation(self, node_id: str) -> list[ScenarioResult]:
        results = [self.node_removal(node_id)]
        node = self._nodes_by_id.get(node_id)
        if node:
            if node.node_type == NodeType.VENDOR:
                results.append(self.vendor_outage(node_id))
            elif node.node_type == NodeType.CONTRACT_CLAUSE:
                results.append(self.clause_invalidation(node_id))
            elif node.node_type == NodeType.PERSON:
                results.append(self.leadership_absence(node_id))
            elif node.node_type == NodeType.ASSUMPTION:
                results.append(self.assumption_failure(node_id))
            results.append(self.delay_injection(node_id))
            results.append(self.cost_shock(node_id))
        return results
