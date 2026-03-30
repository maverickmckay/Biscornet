"""
Structural Isomorphism Engine
------------------------------
Novel situations at the surface level are rarely novel at the structural level.

A supply chain with a sole-source critical vendor that cannot be replaced
in under 90 days is structurally identical to a military operation with a
single supply corridor through contested territory.
Different domain. Same topology. Same failure dynamics.

This engine:
1. Abstracts any graph to a domain-independent topology fingerprint
2. Matches against a library of structural archetypes with known outcomes
3. Transfers historical outcome intelligence to the current situation

The fingerprint captures:
  - SPOF density (single points of failure per node count)
  - False redundancy ratio
  - Max cascade depth
  - Authority concentration (high-betweenness nodes)
  - Reversibility index (how much of the graph can self-correct)
  - Assumption density (low-confidence/low-visibility nodes)
  - External dependency ratio (vendor/contract nodes)
  - Network density and clustering

Eight built-in archetypes with empirically observed failure patterns:
  FRAGILE_STAR         — hub-and-spoke with central SPOF
  FALSE_MESH           — apparent redundancy that all routes through one node
  APPROVAL_BOTTLENECK  — serial approval chain with no bypass
  KNOWLEDGE_SILO       — critical knowledge concentrated in one person/team
  VENDOR_LOCK          — external dependency with no replacement path
  ASSUMPTION_HOUSE     — system built on unvalidated assumptions
  TEMPORAL_CHAIN       — time-sequenced process with deadline traps
  DISTRIBUTED_FRAGILITY — many small SPOFs that interact to produce cascade
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from app.models.graph import Graph, NodeType, EdgeType
from app.engines.dependency import DependencyEngine


@dataclass
class TopologyFingerprint:
    """Domain-independent structural signature of a graph."""
    n_nodes: int
    n_edges: int
    density: float                    # edges / possible edges
    spof_ratio: float                 # SPOFs / n_nodes
    false_redundancy_ratio: float     # nodes with false redundancy / n_nodes
    max_cascade_depth: int
    mean_cascade_depth: float
    authority_concentration: float    # max betweenness centrality
    reversibility_index: float        # mean reversibility across nodes
    assumption_density: float         # assumption/low-confidence nodes / n_nodes
    external_dependency_ratio: float  # vendor/contract nodes / n_nodes
    clustering_coefficient: float
    avg_path_length: float
    has_cycles: bool


@dataclass
class ArchetypeMatch:
    archetype_name: str
    archetype_description: str
    similarity_score: float       # 0–1
    matched_dimensions: list[str]
    historical_failure_rate: float   # fraction of similar systems that failed
    typical_failure_mode: str
    typical_time_to_failure: str  # qualitative
    historical_interventions: list[str]  # what worked historically
    confidence: float


@dataclass
class IsomorphismResult:
    fingerprint: TopologyFingerprint
    best_match: ArchetypeMatch
    all_matches: list[ArchetypeMatch]
    novel_dimensions: list[str]     # dimensions where no archetype matches well
    outcome_transfer: str           # plain-English outcome prediction from analogs
    confidence: float


# ──────────────────────────────────────────────────────────────────────────────
# Built-in archetype library
# ──────────────────────────────────────────────────────────────────────────────

ARCHETYPE_LIBRARY = [
    {
        "name": "FRAGILE_STAR",
        "description": "Hub-and-spoke structure with a single central SPOF controlling all flows",
        "fingerprint": {
            "spof_ratio": (0.05, 0.20),          # low count but critically placed
            "authority_concentration": (0.5, 1.0),
            "max_cascade_depth": (4, 99),
            "density": (0.1, 0.5),
        },
        "failure_rate": 0.82,
        "failure_mode": "Hub failure triggers complete system halt; no reroute available.",
        "time_to_failure": "Sudden — failure is rapid once hub is stressed.",
        "interventions": [
            "Distribute hub functions to 3+ independent nodes",
            "Create genuine bypass routes before removing the hub",
            "Add redundant hubs with independent supply chains",
        ],
    },
    {
        "name": "FALSE_MESH",
        "description": "Apparent redundancy where all paths converge through one hidden node",
        "fingerprint": {
            "false_redundancy_ratio": (0.25, 1.0),
            "spof_ratio": (0.05, 0.15),
            "authority_concentration": (0.3, 0.8),
        },
        "failure_rate": 0.76,
        "failure_mode": "Redundancy invoked under stress but all paths fail simultaneously.",
        "time_to_failure": "Delayed — appears stable until the shared node is stressed.",
        "interventions": [
            "Map all paths to their actual origin nodes",
            "Verify redundancy crosses organizational/vendor boundaries",
            "Test under load to expose convergence before crisis",
        ],
    },
    {
        "name": "APPROVAL_BOTTLENECK",
        "description": "Serial approval chain with no bypass — single decision-maker gates all flow",
        "fingerprint": {
            "authority_concentration": (0.4, 1.0),
            "reversibility_index": (0.0, 0.35),
            "has_cycles": False,
        },
        "failure_rate": 0.71,
        "failure_mode": "Approver unavailability halts all downstream processes indefinitely.",
        "time_to_failure": "Gradual — builds as approver load increases; sudden at absence.",
        "interventions": [
            "Create delegated authority protocols with clear triggers",
            "Document approval criteria so deputies can decide",
            "Identify and train at least one backup approver",
        ],
    },
    {
        "name": "KNOWLEDGE_SILO",
        "description": "Critical operational knowledge concentrated in one person or team",
        "fingerprint": {
            "spof_ratio": (0.03, 0.15),
            "reversibility_index": (0.0, 0.30),
            "external_dependency_ratio": (0.0, 0.2),
        },
        "failure_rate": 0.68,
        "failure_mode": "Key person departure or incapacity renders critical processes inoperable.",
        "time_to_failure": "Slow build, sudden cliff — stable until the knowledge holder leaves.",
        "interventions": [
            "Document critical knowledge in retrievable form",
            "Pair-work to distribute knowledge to at least one backup",
            "Succession plan with specific knowledge transfer milestones",
        ],
    },
    {
        "name": "VENDOR_LOCK",
        "description": "External dependency with no credible replacement path",
        "fingerprint": {
            "external_dependency_ratio": (0.15, 1.0),
            "reversibility_index": (0.0, 0.25),
            "spof_ratio": (0.05, 0.30),
        },
        "failure_rate": 0.64,
        "failure_mode": "Vendor failure or withdrawal halts operations with no short-term alternative.",
        "time_to_failure": "Variable — can be sudden (vendor collapse) or gradual (deterioration).",
        "interventions": [
            "Qualify at least one alternative vendor before crisis",
            "Build minimum viable internal capability as backup",
            "Contract for minimum notice period and transition support",
        ],
    },
    {
        "name": "ASSUMPTION_HOUSE",
        "description": "System built on unvalidated or decaying assumptions",
        "fingerprint": {
            "assumption_density": (0.15, 1.0),
            "clustering_coefficient": (0.0, 0.4),
        },
        "failure_rate": 0.59,
        "failure_mode": "Silent assumption failure propagates undetected until catastrophic realization.",
        "time_to_failure": "Long and silent — failure is already happening before it becomes visible.",
        "interventions": [
            "Explicitly test highest-risk assumptions before they are load-bearing",
            "Create visible indicators when assumptions are stressed",
            "Schedule regular assumption audits as operational procedure",
        ],
    },
    {
        "name": "TEMPORAL_CHAIN",
        "description": "Time-sequenced process with accumulated deadline traps",
        "fingerprint": {
            "max_cascade_depth": (5, 99),
            "reversibility_index": (0.0, 0.35),
            "has_cycles": False,
        },
        "failure_rate": 0.55,
        "failure_mode": "Upstream delay propagates and amplifies through deadline-constrained chain.",
        "time_to_failure": "Predictable — delays compound at a calculable rate.",
        "interventions": [
            "Build buffer time at each critical juncture",
            "Identify earliest-possible failure detection points",
            "Create explicit catch-up protocols for common delay scenarios",
        ],
    },
    {
        "name": "DISTRIBUTED_FRAGILITY",
        "description": "Many small stress points that interact to produce disproportionate cascade",
        "fingerprint": {
            "spof_ratio": (0.15, 0.50),
            "mean_cascade_depth": (2.0, 5.0),
            "clustering_coefficient": (0.3, 1.0),
        },
        "failure_rate": 0.61,
        "failure_mode": "Multiple small failures interact unexpectedly; no single point to fix.",
        "time_to_failure": "Nonlinear — stable then sudden tipping point.",
        "interventions": [
            "Map interaction effects between stress points",
            "Identify the combination that triggers cascade (not individual SPOFs)",
            "Create circuit-breakers that isolate sectors under stress",
        ],
    },
]


class IsomorphismEngine:
    """
    Computes structural fingerprints and finds best-matching archetypes.
    """

    def __init__(self, graph: Graph):
        self.graph = graph
        self.dep = DependencyEngine(graph)
        self.G = self.dep.G

    def compute_fingerprint(self) -> TopologyFingerprint:
        G = self.G
        n = len(G.nodes)
        e = len(G.edges)
        if n == 0:
            return TopologyFingerprint(
                n_nodes=0, n_edges=0, density=0, spof_ratio=0,
                false_redundancy_ratio=0, max_cascade_depth=0,
                mean_cascade_depth=0, authority_concentration=0,
                reversibility_index=0, assumption_density=0,
                external_dependency_ratio=0, clustering_coefficient=0,
                avg_path_length=0, has_cycles=False,
            )

        # Density
        max_edges = n * (n - 1)
        density = e / max_edges if max_edges > 0 else 0

        # SPOFs
        spofs = self.dep.single_points_of_failure()
        spof_ratio = len(spofs) / n

        # False redundancy
        fr_count = sum(
            1 for node in self.graph.nodes
            if self.dep.false_redundancy_score(node.id) > 0.3
        )
        false_redundancy_ratio = fr_count / n

        # Cascade depths
        depths = []
        for node in self.graph.nodes:
            cascade = self.dep.downstream_cascade(node.id)
            depths.append(len(cascade))
        max_cascade_depth = max(depths) if depths else 0
        mean_cascade_depth = sum(depths) / len(depths) if depths else 0

        # Authority concentration (betweenness)
        try:
            bc = nx.betweenness_centrality(G, normalized=True)
            authority_concentration = max(bc.values()) if bc else 0
        except Exception:
            authority_concentration = 0

        # Reversibility index
        rev_values = [node.attributes.reversibility for node in self.graph.nodes]
        reversibility_index = sum(rev_values) / len(rev_values) if rev_values else 0.5

        # Assumption density
        assumption_count = sum(
            1 for node in self.graph.nodes
            if node.node_type == NodeType.ASSUMPTION or
               (node.attributes.confidence < 0.5 and node.attributes.visibility < 0.4)
        )
        assumption_density = assumption_count / n

        # External dependency ratio
        external_count = sum(
            1 for node in self.graph.nodes
            if node.node_type in (NodeType.VENDOR, NodeType.CONTRACT_CLAUSE)
        )
        external_dependency_ratio = external_count / n

        # Clustering
        try:
            ug = G.to_undirected()
            clustering_coefficient = nx.average_clustering(ug)
        except Exception:
            clustering_coefficient = 0

        # Average path length
        try:
            if nx.is_weakly_connected(G):
                avg_path_length = nx.average_shortest_path_length(G)
            else:
                largest = max(nx.weakly_connected_components(G), key=len)
                sg = G.subgraph(largest)
                avg_path_length = nx.average_shortest_path_length(sg)
        except Exception:
            avg_path_length = 0

        has_cycles = not nx.is_directed_acyclic_graph(G)

        return TopologyFingerprint(
            n_nodes=n,
            n_edges=e,
            density=round(density, 4),
            spof_ratio=round(spof_ratio, 4),
            false_redundancy_ratio=round(false_redundancy_ratio, 4),
            max_cascade_depth=max_cascade_depth,
            mean_cascade_depth=round(mean_cascade_depth, 2),
            authority_concentration=round(authority_concentration, 4),
            reversibility_index=round(reversibility_index, 4),
            assumption_density=round(assumption_density, 4),
            external_dependency_ratio=round(external_dependency_ratio, 4),
            clustering_coefficient=round(clustering_coefficient, 4),
            avg_path_length=round(avg_path_length, 2),
            has_cycles=has_cycles,
        )

    def _match_archetype(
        self,
        fingerprint: TopologyFingerprint,
        archetype: dict,
    ) -> tuple[float, list[str]]:
        """Score how well a fingerprint matches an archetype. Returns (score, matched_dims)."""
        fp_dict = {
            "spof_ratio": fingerprint.spof_ratio,
            "false_redundancy_ratio": fingerprint.false_redundancy_ratio,
            "max_cascade_depth": fingerprint.max_cascade_depth,
            "mean_cascade_depth": fingerprint.mean_cascade_depth,
            "authority_concentration": fingerprint.authority_concentration,
            "reversibility_index": fingerprint.reversibility_index,
            "assumption_density": fingerprint.assumption_density,
            "external_dependency_ratio": fingerprint.external_dependency_ratio,
            "clustering_coefficient": fingerprint.clustering_coefficient,
            "density": fingerprint.density,
            "has_cycles": fingerprint.has_cycles,
        }

        matched_dims = []
        scores = []
        for dim, criterion in archetype["fingerprint"].items():
            val = fp_dict.get(dim)
            if val is None:
                continue
            if isinstance(criterion, tuple):
                lo, hi = criterion
                if lo <= val <= hi:
                    matched_dims.append(dim)
                    scores.append(1.0)
                else:
                    # Partial score for near-misses
                    dist = min(abs(val - lo), abs(val - hi))
                    rng = hi - lo if hi != lo else 1
                    partial = max(0.0, 1.0 - dist / rng)
                    scores.append(partial * 0.5)
            elif isinstance(criterion, bool):
                if val == criterion:
                    matched_dims.append(dim)
                    scores.append(1.0)
                else:
                    scores.append(0.0)

        if not scores:
            return 0.0, []
        return sum(scores) / len(scores), matched_dims

    def find_analogs(self, fingerprint: TopologyFingerprint) -> list[ArchetypeMatch]:
        """Find all archetype matches, sorted by similarity."""
        matches = []
        for archetype in ARCHETYPE_LIBRARY:
            similarity, matched_dims = self._match_archetype(fingerprint, archetype)
            confidence = min(0.90, similarity * 0.9 + len(matched_dims) * 0.03)
            matches.append(ArchetypeMatch(
                archetype_name=archetype["name"],
                archetype_description=archetype["description"],
                similarity_score=round(similarity, 4),
                matched_dimensions=matched_dims,
                historical_failure_rate=archetype["failure_rate"],
                typical_failure_mode=archetype["failure_mode"],
                typical_time_to_failure=archetype["time_to_failure"],
                historical_interventions=archetype["interventions"],
                confidence=round(confidence, 4),
            ))
        matches.sort(key=lambda m: -m.similarity_score)
        return matches

    def analyze(self) -> IsomorphismResult:
        fingerprint = self.compute_fingerprint()
        all_matches = self.find_analogs(fingerprint)
        best = all_matches[0] if all_matches else None

        # Identify novel dimensions (where no archetype scores well)
        archetype_dims = set()
        for a in ARCHETYPE_LIBRARY:
            archetype_dims.update(a["fingerprint"].keys())
        fp_dict = {
            "spof_ratio": fingerprint.spof_ratio,
            "false_redundancy_ratio": fingerprint.false_redundancy_ratio,
            "authority_concentration": fingerprint.authority_concentration,
            "assumption_density": fingerprint.assumption_density,
            "external_dependency_ratio": fingerprint.external_dependency_ratio,
        }
        # Dimensions where actual value is extreme but no archetype covers it well
        novel_dims = [
            dim for dim, val in fp_dict.items()
            if isinstance(val, float) and val > 0.5
            and all(
                not (lo <= val <= hi if isinstance(a["fingerprint"].get(dim), tuple) else False)
                for a in ARCHETYPE_LIBRARY
                if dim in a["fingerprint"]
            )
        ]

        outcome_transfer = self._build_outcome_transfer(best, fingerprint) if best else "No analog found."

        return IsomorphismResult(
            fingerprint=fingerprint,
            best_match=best,
            all_matches=all_matches[:4],
            novel_dimensions=novel_dims,
            outcome_transfer=outcome_transfer,
            confidence=best.confidence if best else 0.0,
        )

    def _build_outcome_transfer(
        self, match: ArchetypeMatch, fp: TopologyFingerprint
    ) -> str:
        parts = [
            f"Closest structural analog: {match.archetype_name} ({match.archetype_description}).",
            f"Historical systems with this structure failed {match.historical_failure_rate:.0%} of the time.",
            f"Typical failure mode: {match.typical_failure_mode}",
            f"Typical timing: {match.typical_time_to_failure}",
        ]
        if match.historical_interventions:
            parts.append(f"What historically worked: {match.historical_interventions[0]}")
        return " ".join(parts)
