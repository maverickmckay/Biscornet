"""
Causal Mechanism Engine
-----------------------
Extends NNM's dependency graph with explicit causal relationships.

Instead of just knowing "A depends on B", the causal layer encodes WHY:
  - What mechanism connects them
  - What conditions activate the dependency
  - What lag exists between cause and effect
  - What the direction and strength of causal influence is

This allows reasoning FROM mechanisms to consequences, not just FROM
historical patterns — enabling prediction in novel situations where
no historical analog exists.

Mechanism types:
  APPROVAL_GATES    — B must approve before A can proceed
  RESOURCE_FEEDS    — B supplies a resource A consumes
  AUTHORITY_GRANTS  — B holds authority that A requires
  INFORMATION_FLOWS — B produces information A depends on
  TIMING_CONSTRAINS — B's schedule constrains when A can act
  FINANCIAL_FUNDS   — B provides funding that keeps A active
  KNOWLEDGE_HOLDS   — B holds knowledge A cannot replicate quickly
  TRUST_ANCHORS     — B provides legitimacy/trust A uses
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import networkx as nx

from app.models.graph import Graph, EdgeType


class MechanismType(str, Enum):
    APPROVAL_GATES   = "approval_gates"
    RESOURCE_FEEDS   = "resource_feeds"
    AUTHORITY_GRANTS = "authority_grants"
    INFORMATION_FLOWS = "information_flows"
    TIMING_CONSTRAINS = "timing_constrains"
    FINANCIAL_FUNDS  = "financial_funds"
    KNOWLEDGE_HOLDS  = "knowledge_holds"
    TRUST_ANCHORS    = "trust_anchors"
    UNKNOWN          = "unknown"


# Map from structural EdgeType to most likely CausalMechanism
_EDGE_MECHANISM_MAP: dict[EdgeType, MechanismType] = {
    EdgeType.APPROVES:      MechanismType.APPROVAL_GATES,
    EdgeType.FUNDS:         MechanismType.FINANCIAL_FUNDS,
    EdgeType.INFORMS:       MechanismType.INFORMATION_FLOWS,
    EdgeType.BLOCKS:        MechanismType.APPROVAL_GATES,
    EdgeType.ESCALATES_TO:  MechanismType.AUTHORITY_GRANTS,
    EdgeType.GOVERNED_BY:   MechanismType.AUTHORITY_GRANTS,
    EdgeType.TIMED_BEFORE:  MechanismType.TIMING_CONSTRAINS,
    EdgeType.DEPENDS_ON:    MechanismType.RESOURCE_FEEDS,
    EdgeType.SUBSTITUTES:   MechanismType.RESOURCE_FEEDS,
    EdgeType.CONTINGENT_ON: MechanismType.APPROVAL_GATES,
}

# Mechanism failure lag — how quickly does downstream notice upstream failure?
# In hours. Low = immediate; high = delayed discovery.
_MECHANISM_LAG_HOURS: dict[MechanismType, float] = {
    MechanismType.APPROVAL_GATES:    0.5,
    MechanismType.RESOURCE_FEEDS:    2.0,
    MechanismType.AUTHORITY_GRANTS:  4.0,
    MechanismType.INFORMATION_FLOWS: 1.0,
    MechanismType.TIMING_CONSTRAINS: 8.0,
    MechanismType.FINANCIAL_FUNDS:   24.0,
    MechanismType.KNOWLEDGE_HOLDS:   48.0,
    MechanismType.TRUST_ANCHORS:     12.0,
    MechanismType.UNKNOWN:           6.0,
}

# Mechanism strength — how directly does failure propagate?
_MECHANISM_STRENGTH: dict[MechanismType, float] = {
    MechanismType.APPROVAL_GATES:    0.95,
    MechanismType.RESOURCE_FEEDS:    0.85,
    MechanismType.AUTHORITY_GRANTS:  0.80,
    MechanismType.INFORMATION_FLOWS: 0.70,
    MechanismType.TIMING_CONSTRAINS: 0.60,
    MechanismType.FINANCIAL_FUNDS:   0.90,
    MechanismType.KNOWLEDGE_HOLDS:   0.75,
    MechanismType.TRUST_ANCHORS:     0.65,
    MechanismType.UNKNOWN:           0.70,
}


@dataclass
class CausalEdge:
    source: str
    target: str
    mechanism: MechanismType
    lag_hours: float
    strength: float           # 0-1, how directly does failure propagate
    reversible: bool = True   # can the dependency be severed?
    conditions: list[str] = field(default_factory=list)  # when is it active?


@dataclass
class CausalChain:
    """A sequence of causally connected nodes leading to a predicted failure."""
    origin_node: str
    chain: list[str]           # ordered sequence of nodes
    mechanisms: list[MechanismType]
    cumulative_lag_hours: float
    cumulative_strength: float  # product of strengths along chain
    failure_mode: str
    confidence: float


@dataclass
class CausalAnalysis:
    causal_edges: list[CausalEdge]
    failure_chains: list[CausalChain]
    mechanism_summary: dict[str, MechanismType]  # node_id → dominant mechanism type
    highest_strength_paths: list[CausalChain]
    novel_risk_nodes: list[str]  # nodes whose risk comes from mechanism, not just topology


class CausalEngine:
    """
    Builds and reasons over the causal mechanism layer of a graph.

    The causal layer augments structural dependencies with WHY and HOW
    they propagate — enabling forward reasoning about failure sequences
    that topology alone cannot provide.
    """

    def __init__(self, graph: Graph):
        self.graph = graph
        self.G = self._build_nx()
        self.causal_edges = self._infer_causal_edges()
        self._cg = self._build_causal_nx()

    def _build_nx(self) -> nx.DiGraph:
        G = nx.DiGraph()
        for n in self.graph.nodes:
            G.add_node(n.id, label=n.label, node_type=n.node_type.value,
                       criticality=n.attributes.criticality,
                       replaceability=n.attributes.replaceability)
        for e in self.graph.edges:
            G.add_edge(e.source, e.target,
                       edge_type=e.edge_type.value,
                       reliability=e.attributes.reliability)
        return G

    def _infer_causal_edges(self) -> list[CausalEdge]:
        """Infer causal mechanism from structural edge type."""
        edges = []
        for e in self.graph.edges:
            mech = _EDGE_MECHANISM_MAP.get(e.edge_type, MechanismType.UNKNOWN)
            # Override for high-criticality, low-replaceability targets
            target_node = next((n for n in self.graph.nodes if n.id == e.target), None)
            if target_node:
                if target_node.attributes.replaceability < 0.2:
                    # Hard-to-replace targets make the mechanism a knowledge/authority hold
                    if mech == MechanismType.RESOURCE_FEEDS:
                        mech = MechanismType.KNOWLEDGE_HOLDS
            edges.append(CausalEdge(
                source=e.source,
                target=e.target,
                mechanism=mech,
                lag_hours=_MECHANISM_LAG_HOURS[mech] * (2.0 - e.attributes.reliability),
                strength=_MECHANISM_STRENGTH[mech] * e.attributes.reliability,
                reversible=target_node.attributes.replaceability > 0.3 if target_node else True,
            ))
        return edges

    def _build_causal_nx(self) -> nx.DiGraph:
        cg = nx.DiGraph()
        for e in self.causal_edges:
            cg.add_edge(e.source, e.target,
                        mechanism=e.mechanism.value,
                        lag=e.lag_hours,
                        strength=e.strength,
                        reversible=e.reversible)
        return cg

    def failure_chains_from(
        self,
        node_id: str,
        max_depth: int = 6,
        min_strength: float = 0.3,
    ) -> list[CausalChain]:
        """
        Trace all causal failure chains originating from node_id.
        Returns chains ordered by cumulative strength (most dangerous first).
        """
        chains: list[CausalChain] = []

        def dfs(current: str, path: list[str], mechs: list[MechanismType],
                cum_lag: float, cum_strength: float):
            if len(path) > max_depth:
                return
            for succ in self._cg.successors(current):
                if succ in path:
                    continue
                edge = self._cg[current][succ]
                new_strength = cum_strength * edge["strength"]
                if new_strength < min_strength:
                    continue
                new_lag = cum_lag + edge["lag"]
                new_mechs = mechs + [MechanismType(edge["mechanism"])]
                new_path = path + [succ]
                # Determine failure mode from dominant mechanism
                dom_mech = max(set(new_mechs), key=new_mechs.count)
                failure_mode = self._failure_mode_label(dom_mech)
                chains.append(CausalChain(
                    origin_node=node_id,
                    chain=new_path,
                    mechanisms=new_mechs,
                    cumulative_lag_hours=round(new_lag, 2),
                    cumulative_strength=round(new_strength, 4),
                    failure_mode=failure_mode,
                    confidence=round(min(0.95, new_strength), 4),
                ))
                dfs(succ, new_path, new_mechs, new_lag, new_strength)

        if node_id in self._cg:
            dfs(node_id, [node_id], [], 0.0, 1.0)

        chains.sort(key=lambda c: -c.cumulative_strength)
        return chains

    def _failure_mode_label(self, mech: MechanismType) -> str:
        labels = {
            MechanismType.APPROVAL_GATES:    "approval bottleneck cascade",
            MechanismType.RESOURCE_FEEDS:    "resource starvation cascade",
            MechanismType.AUTHORITY_GRANTS:  "authority vacuum cascade",
            MechanismType.INFORMATION_FLOWS: "information blackout cascade",
            MechanismType.TIMING_CONSTRAINS: "scheduling deadlock cascade",
            MechanismType.FINANCIAL_FUNDS:   "funding withdrawal cascade",
            MechanismType.KNOWLEDGE_HOLDS:   "knowledge lock-in cascade",
            MechanismType.TRUST_ANCHORS:     "legitimacy collapse cascade",
            MechanismType.UNKNOWN:           "dependency cascade",
        }
        return labels.get(mech, "cascade failure")

    def dominant_mechanism(self, node_id: str) -> MechanismType:
        """Most impactful mechanism operating through this node."""
        mechs = [MechanismType(self._cg[node_id][s]["mechanism"])
                 for s in self._cg.successors(node_id)
                 if node_id in self._cg]
        if not mechs:
            return MechanismType.UNKNOWN
        return max(set(mechs), key=mechs.count)

    def novel_risk_nodes(self) -> list[str]:
        """
        Nodes whose causal risk is disproportionate to their structural visibility.
        High mechanism strength but low in-degree = hidden causal load-bearers.
        """
        result = []
        for n in self.graph.nodes:
            nid = n.id
            if nid not in self._cg:
                continue
            # Total outgoing causal strength
            out_strength = sum(
                self._cg[nid][s]["strength"] for s in self._cg.successors(nid)
            )
            # Structural in-degree (how obvious the dependency is)
            struct_in = self.G.in_degree(nid)
            # If high outgoing causal strength but low structural visibility
            if out_strength > 1.0 and struct_in <= 1:
                result.append(nid)
        return result

    def analyze(self) -> CausalAnalysis:
        all_chains = []
        for n in self.graph.nodes:
            chains = self.failure_chains_from(n.id, max_depth=5)
            all_chains.extend(chains[:3])  # top 3 per node

        all_chains.sort(key=lambda c: -c.cumulative_strength)
        highest = all_chains[:10]

        mechanism_summary = {
            n.id: self.dominant_mechanism(n.id)
            for n in self.graph.nodes
        }

        return CausalAnalysis(
            causal_edges=self.causal_edges,
            failure_chains=all_chains[:50],
            mechanism_summary=mechanism_summary,
            highest_strength_paths=highest,
            novel_risk_nodes=self.novel_risk_nodes(),
        )
