"""
Flow Engine
-----------
Tracks five flow types across the graph:
  - Decision flow
  - Information flow
  - Money/resource flow
  - Obligation flow
  - Feedback flow

Detects:
  - Dead ends (no outgoing path to a terminal/output)
  - Broken return loops (feedback path severed)
  - Isolated load (a node absorbs flow with no redistribution)
  - Timing traps (sequential delays that compound to miss a deadline)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from app.models.graph import Graph, EdgeType


# Flow edge type sets
DECISION_EDGES = {EdgeType.APPROVES, EdgeType.ESCALATES_TO, EdgeType.GOVERNED_BY}
INFORMATION_EDGES = {EdgeType.INFORMS, EdgeType.GOVERNED_BY}
RESOURCE_EDGES = {EdgeType.FUNDS, EdgeType.DEPENDS_ON}
OBLIGATION_EDGES = {EdgeType.CONTINGENT_ON, EdgeType.GOVERNED_BY, EdgeType.TIMED_BEFORE}
FEEDBACK_EDGES = {EdgeType.INFORMS, EdgeType.ESCALATES_TO}


@dataclass
class FlowIssue:
    kind: str           # "dead_end" | "broken_loop" | "isolated_load" | "timing_trap"
    node_ids: list[str]
    description: str
    severity: float = 0.5   # 0-1


class FlowEngine:
    """Analyses flow properties of the dependency graph."""

    def __init__(self, graph: Graph):
        self.model = graph
        self.G = self._build_nx()

    def _build_nx(self) -> nx.DiGraph:
        G = nx.DiGraph()
        for node in self.model.nodes:
            G.add_node(node.id, label=node.label, node_type=node.node_type.value,
                       load=node.attributes.load,
                       time_sensitivity=node.attributes.time_sensitivity)
        for edge in self.model.edges:
            G.add_edge(
                edge.source, edge.target,
                edge_type=edge.edge_type.value,
                weight=edge.attributes.weight,
                latency=edge.attributes.latency,
                reliability=edge.attributes.reliability,
            )
        return G

    # ------------------------------------------------------------------
    # Subgraph by flow type
    # ------------------------------------------------------------------

    def _flow_subgraph(self, edge_types: set[EdgeType]) -> nx.DiGraph:
        type_values = {e.value for e in edge_types}
        edges = [(u, v, d) for u, v, d in self.G.edges(data=True)
                 if d.get("edge_type") in type_values]
        sg = nx.DiGraph()
        sg.add_nodes_from(self.G.nodes(data=True))
        sg.add_edges_from(edges)
        return sg

    # ------------------------------------------------------------------
    # Dead end detection
    # ------------------------------------------------------------------

    def dead_ends(self) -> list[FlowIssue]:
        """
        Nodes that receive flow but have no outgoing flow path to any
        terminal (out-degree 0 node in the overall graph).
        """
        issues: list[FlowIssue] = []
        terminals = {n for n in self.G.nodes if self.G.out_degree(n) == 0}

        for node in self.G.nodes:
            if self.G.in_degree(node) == 0:
                continue  # source node, not a dead end
            if node in terminals:
                continue  # this IS a terminal
            # Check if any terminal is reachable
            reachable = any(nx.has_path(self.G, node, t) for t in terminals)
            if not reachable:
                label = self.G.nodes[node].get("label", node)
                issues.append(FlowIssue(
                    kind="dead_end",
                    node_ids=[node],
                    description=f"'{label}' receives flow but cannot reach any terminal — flow is trapped.",
                    severity=0.8,
                ))
        return issues

    # ------------------------------------------------------------------
    # Broken return loops
    # ------------------------------------------------------------------

    def broken_return_loops(self) -> list[FlowIssue]:
        """
        Nodes that emit feedback/information but the recipient has no
        path back to the origin (unidirectional information asymmetry).
        """
        issues: list[FlowIssue] = []
        fb_graph = self._flow_subgraph(FEEDBACK_EDGES)

        for u, v in fb_graph.edges():
            # There is a feedback edge u → v.  Is there a return path v → u?
            if not nx.has_path(fb_graph, v, u):
                u_label = self.G.nodes[u].get("label", u)
                v_label = self.G.nodes[v].get("label", v)
                issues.append(FlowIssue(
                    kind="broken_loop",
                    node_ids=[u, v],
                    description=(
                        f"'{u_label}' sends to '{v_label}' but no return path exists — "
                        "feedback loop is broken."
                    ),
                    severity=0.6,
                ))
        return issues

    # ------------------------------------------------------------------
    # Isolated load
    # ------------------------------------------------------------------

    def isolated_load(self) -> list[FlowIssue]:
        """
        Nodes with high load that have no outgoing edges to distribute it.
        """
        issues: list[FlowIssue] = []
        for node, data in self.G.nodes(data=True):
            load = data.get("load", 0.0)
            if load > 0.75 and self.G.out_degree(node) == 0:
                label = data.get("label", node)
                issues.append(FlowIssue(
                    kind="isolated_load",
                    node_ids=[node],
                    description=(
                        f"'{label}' has load={load:.0%} with no outgoing distribution path — "
                        "pressure localises here."
                    ),
                    severity=load,
                ))
        return issues

    # ------------------------------------------------------------------
    # Timing traps
    # ------------------------------------------------------------------

    def timing_traps(self, deadline_hours: float = 24.0) -> list[FlowIssue]:
        """
        Sequential paths where cumulative latency exceeds deadline_hours.
        """
        issues: list[FlowIssue] = []
        # Find all simple paths from sources to sinks
        sources = [n for n in self.G.nodes if self.G.in_degree(n) == 0]
        sinks = [n for n in self.G.nodes if self.G.out_degree(n) == 0]

        for source in sources:
            for sink in sinks:
                try:
                    for path in nx.all_simple_paths(self.G, source, sink, cutoff=15):
                        total_latency = sum(
                            self.G[path[i]][path[i + 1]].get("latency", 0.0)
                            for i in range(len(path) - 1)
                        )
                        if total_latency > deadline_hours:
                            labels = [self.G.nodes[n].get("label", n) for n in path]
                            issues.append(FlowIssue(
                                kind="timing_trap",
                                node_ids=path,
                                description=(
                                    f"Path {' → '.join(labels)} accumulates "
                                    f"{total_latency:.1f}h latency (deadline={deadline_hours}h)."
                                ),
                                severity=min(1.0, total_latency / (deadline_hours * 2)),
                            ))
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    pass
        return issues

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    def all_issues(self, deadline_hours: float = 24.0) -> list[FlowIssue]:
        issues = []
        issues.extend(self.dead_ends())
        issues.extend(self.broken_return_loops())
        issues.extend(self.isolated_load())
        issues.extend(self.timing_traps(deadline_hours))
        return issues

    def per_node_flow_severity(self) -> dict[str, float]:
        """Maximum flow severity touching each node."""
        severity: dict[str, float] = {n: 0.0 for n in self.G.nodes}
        for issue in self.all_issues():
            for nid in issue.node_ids:
                if nid in severity:
                    severity[nid] = max(severity[nid], issue.severity)
        return severity
