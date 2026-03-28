"""
Dependency Graph Engine
-----------------------
Builds a directed graph from the data model and runs structural analysis:
- Single points of failure (SPOF)
- False redundancy detection
- Hidden chokepoints
- Cycles with no exit
- Dead ends
"""
from __future__ import annotations

import math
from typing import Optional
import networkx as nx

from app.models.graph import Graph, Node, Edge, NodeType


class DependencyEngine:
    """Wraps a NetworkX DiGraph with collapse-analysis methods."""

    def __init__(self, graph: Graph):
        self.model = graph
        self.G = self._build_nx()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

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
                confidence=node.attributes.confidence,
                visibility=node.attributes.visibility,
            )
        for edge in self.model.edges:
            G.add_edge(
                edge.source,
                edge.target,
                edge_type=edge.edge_type.value,
                weight=edge.attributes.weight,
                reliability=edge.attributes.reliability,
                latency=edge.attributes.latency,
                reversible=edge.attributes.reversible,
            )
        return G

    # ------------------------------------------------------------------
    # Core structural queries
    # ------------------------------------------------------------------

    def single_points_of_failure(self) -> list[str]:
        """
        Articulation points in the undirected projection.
        Removal disconnects the graph.
        """
        undirected = self.G.to_undirected()
        if undirected.number_of_nodes() < 2:
            return []
        return list(nx.articulation_points(undirected))

    def dead_ends(self) -> list[str]:
        """Nodes with no outgoing edges (sinks) that are not leaf resources."""
        return [n for n in self.G.nodes if self.G.out_degree(n) == 0 and self.G.in_degree(n) > 0]

    def cycles_no_exit(self) -> list[list[str]]:
        """Strongly connected components of size > 1 with no outgoing edges to the rest."""
        sccs = [scc for scc in nx.strongly_connected_components(self.G) if len(scc) > 1]
        trapped = []
        for scc in sccs:
            # Check for any edge leaving the SCC
            exits = [
                (u, v) for u in scc for v in self.G.successors(u) if v not in scc
            ]
            if not exits:
                trapped.append(list(scc))
        return trapped

    def reroute_availability(self, node_id: str) -> float:
        """
        Score 0-1: what fraction of dependent nodes still have a path
        to an original sink after removing node_id.
        1.0 = fully reroutable, 0.0 = total blockage.
        """
        if node_id not in self.G:
            return 1.0
        dependents = list(self.G.predecessors(node_id))
        if not dependents:
            return 1.0

        # Use the *original* graph's sinks as targets — we want to know if
        # dependents can still reach the same final destinations.
        original_sinks = [n for n in self.G.nodes if self.G.out_degree(n) == 0 and n != node_id]

        G_minus = self.G.copy()
        G_minus.remove_node(node_id)

        if not original_sinks:
            return 0.0

        still_reachable = 0
        for dep in dependents:
            if dep not in G_minus:
                continue
            for sink in original_sinks:
                if sink in G_minus and nx.has_path(G_minus, dep, sink):
                    still_reachable += 1
                    break

        return still_reachable / len(dependents)

    def downstream_cascade(self, node_id: str) -> list[str]:
        """All nodes reachable from node_id (will be affected on failure)."""
        if node_id not in self.G:
            return []
        return [n for n in nx.descendants(self.G, node_id) if n != node_id]

    def upstream_dependents(self, node_id: str) -> list[str]:
        """All nodes that have a path TO node_id (will be blocked on failure)."""
        if node_id not in self.G:
            return []
        return [n for n in nx.ancestors(self.G, node_id) if n != node_id]

    # ------------------------------------------------------------------
    # Hidden chokepoint detection
    # ------------------------------------------------------------------

    def conditional_centrality(self, node_id: str) -> float:
        """
        Betweenness centrality of node_id after collapsing its nearest
        high-centrality neighbours.  A node that looks unimportant normally
        but becomes critical after neighbours fail is a hidden chokepoint.
        """
        bc = nx.betweenness_centrality(self.G, normalized=True)
        baseline = bc.get(node_id, 0.0)

        # Remove the top-20% most central neighbours
        neighbours = list(self.G.predecessors(node_id)) + list(self.G.successors(node_id))
        if not neighbours:
            return baseline

        threshold = sorted(bc.values(), reverse=True)[max(0, len(bc) // 5)]
        top_neighbours = [n for n in neighbours if bc.get(n, 0) >= threshold and n != node_id]
        if not top_neighbours:
            return baseline

        G_reduced = self.G.copy()
        G_reduced.remove_nodes_from(top_neighbours)
        if node_id not in G_reduced:
            return 1.0  # became the only bridge

        bc_reduced = nx.betweenness_centrality(G_reduced, normalized=True)
        conditional = bc_reduced.get(node_id, 0.0)
        return conditional

    def hidden_chokepoint_score(self, node_id: str) -> float:
        """
        Delta between conditional and baseline centrality, normalised.
        High score = node is more critical than it appears.
        """
        bc = nx.betweenness_centrality(self.G, normalized=True)
        baseline = bc.get(node_id, 0.0)
        conditional = self.conditional_centrality(node_id)
        # Score is how much the node's importance rises when cover is removed
        delta = max(0.0, conditional - baseline)
        return min(1.0, delta * 5)  # amplify small deltas

    # ------------------------------------------------------------------
    # False redundancy detection
    # ------------------------------------------------------------------

    def false_redundancy_score(self, node_id: str) -> float:
        """
        Check nominally separate paths into node_id.
        If all paths pass through a single shared ancestor, redundancy is false.
        Returns 0.0 = genuinely redundant, 1.0 = completely false redundancy.
        """
        predecessors = list(self.G.predecessors(node_id))
        if len(predecessors) < 2:
            return 0.0  # single input, no redundancy claim

        # For each predecessor find its full ancestor set
        ancestor_sets = [
            set(nx.ancestors(self.G, p)) | {p} for p in predecessors
        ]
        # Shared ancestors present in ALL input paths
        shared = set.intersection(*ancestor_sets) if ancestor_sets else set()
        # Remove node_id itself
        shared.discard(node_id)

        if not shared:
            return 0.0  # no shared ancestor → paths are genuinely independent

        # Score by how many inputs share a bottleneck ancestor
        # Weight by the criticality of the shared ancestor
        max_criticality = max(
            self.G.nodes[n].get("criticality", 0.5) for n in shared
        )
        return max_criticality

    # ------------------------------------------------------------------
    # Pressure absorption
    # ------------------------------------------------------------------

    def pressure_absorption_score(self, node_id: str) -> float:
        """
        How well does the neighbourhood redistribute load if this node is stressed?
        High score = pressure redistributes. Low score = localises.
        """
        successors = list(self.G.successors(node_id))
        if not successors:
            return 0.0

        # Count available substitute paths weighted by reliability
        total_reliability = sum(
            self.G[node_id][s].get("reliability", 1.0) for s in successors
        )
        n_paths = len(successors)
        # Diversity penalty: if only one successor, no absorption
        diversity = (n_paths - 1) / max(n_paths, 1)
        # Average successor replaceability
        avg_replaceability = sum(
            self.G.nodes[s].get("replaceability", 0.5) for s in successors
        ) / n_paths
        return min(1.0, (diversity * 0.5 + avg_replaceability * 0.5) * total_reliability)

    # ------------------------------------------------------------------
    # Reversion mapping
    # ------------------------------------------------------------------

    def reversion_targets(self, node_id: str) -> list[str]:
        """
        When node_id fails, which nodes gain load/authority/relevance?
        These are: substitute nodes, escalation targets, and nodes that
        become newly reachable to upstream dependents.
        """
        targets = set()
        # Direct substitutes in model
        for u, v, data in self.G.edges(data=True):
            if data.get("edge_type") == "substitutes" and (u == node_id or v == node_id):
                targets.add(v if u == node_id else u)
        # Escalation targets
        for u, v, data in self.G.edges(data=True):
            if data.get("edge_type") == "escalates_to" and u == node_id:
                targets.add(v)
        # Nodes that gain centrality after removal (top gainers)
        bc_before = nx.betweenness_centrality(self.G, normalized=True)
        G_minus = self.G.copy()
        if node_id in G_minus:
            G_minus.remove_node(node_id)
        bc_after = nx.betweenness_centrality(G_minus, normalized=True)
        gainers = sorted(
            [(n, bc_after.get(n, 0) - bc_before.get(n, 0)) for n in G_minus.nodes],
            key=lambda x: -x[1],
        )
        for n, gain in gainers[:3]:
            if gain > 0.01:
                targets.add(n)
        return list(targets)
