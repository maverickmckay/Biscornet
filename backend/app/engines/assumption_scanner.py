"""
Assumption Scanner — two-pass implicit assumption detection.

Pass 1 — Structural (always-on, no text required):
  - Low-reliability edges on non-vendor nodes
  - High-dependency nodes with low confidence
  - Dark paths (low visibility chains)
  - Unbreakable contingencies (CONTINGENT_ON edge + replaceability=0)

Pass 2 — Textual (opt-in, requires raw text from document extraction):
  - Assumption language patterns
  - Implicit sequencing assumptions
  - Modal verbs in passive constructions
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import networkx as nx

from app.models.graph import Graph, EdgeType, NodeType


@dataclass
class ImplicitAssumption:
    description: str
    affected_node_ids: list[str]
    scan_type: Literal["structural", "textual"]
    confidence: float = 0.7


@dataclass
class AssumptionScanResult:
    implicit_assumptions: list[ImplicitAssumption]
    structural_count: int
    textual_count: int


# Textual patterns for implicit assumptions
_IMPLICIT_PATTERNS = [
    (re.compile(r"\bthis\s+will\s+not\b", re.I), "Negative assumption detected"),
    (re.compile(r"\bit\s+is\s+expected\s+that\b", re.I), "Expectation asserted without evidence"),
    (re.compile(r"\bassuming\s+normal\b", re.I), "Normal-conditions assumption"),
    (re.compile(r"\bunder\s+current\s+conditions\b", re.I), "Current-conditions assumption (may not hold under stress)"),
    (re.compile(r"\bbarring\s+unforeseen\b", re.I), "Unforeseen-event exclusion (hides tail risk)"),
    (re.compile(r"\bby\s+the\s+time\s+\w+\s+is\s+complete\b", re.I), "Implicit sequencing assumption"),
    (re.compile(r"\bonce\s+\w+\s+(?:is|are)\s+(?:complete|approved|delivered)\b", re.I), "Implicit sequencing assumption"),
    (re.compile(r"\bwhen\s+\w+\s+approves\b", re.I), "Implicit approval sequencing"),
    (re.compile(r"\bshould\s+be\s+available\b", re.I), "Availability asserted without guarantee"),
    (re.compile(r"\bis\s+expected\s+to\s+deliver\b", re.I), "Delivery asserted without guarantee"),
    (re.compile(r"\bwill\s+presumably\b", re.I), "Presumption without commitment"),
    (re.compile(r"\bsubject\s+to\s+(?:market|regulatory|exchange)\b", re.I), "External variable assumption"),
    (re.compile(r"\bprovided\s+that\b", re.I), "Conditional assumption (check if condition is tracked)"),
    (re.compile(r"\bon\s+the\s+assumption\s+that\b", re.I), "Explicit assumption stated but may be untracked"),
]


class AssumptionScanner:
    """Scans for implicit assumptions in graph structure and/or text."""

    def __init__(self, graph: Graph):
        self.graph = graph
        self._node_map = {n.id: n for n in graph.nodes}
        self.G = self._build_nx()

    def _build_nx(self) -> nx.DiGraph:
        G = nx.DiGraph()
        for node in self.graph.nodes:
            G.add_node(
                node.id,
                label=node.label,
                node_type=node.node_type.value,
                confidence=node.attributes.confidence,
                visibility=node.attributes.visibility,
                replaceability=node.attributes.replaceability,
            )
        for edge in self.graph.edges:
            G.add_edge(
                edge.source, edge.target,
                edge_type=edge.edge_type.value,
                reliability=edge.attributes.reliability,
            )
        return G

    # ------------------------------------------------------------------
    # Pass 1: Structural
    # ------------------------------------------------------------------

    def _structural_pass(self) -> list[ImplicitAssumption]:
        results: list[ImplicitAssumption] = []

        # 1a. Low-reliability edges on non-vendor nodes
        for u, v, data in self.G.edges(data=True):
            rel = data.get("reliability", 1.0)
            u_node = self._node_map.get(u)
            if rel < 0.7 and u_node and u_node.node_type not in (NodeType.VENDOR, NodeType.ASSET):
                u_label = self.G.nodes[u].get("label", u)
                v_label = self.G.nodes[v].get("label", v)
                results.append(ImplicitAssumption(
                    description=(
                        f"Edge '{u_label}' → '{v_label}' has reliability {rel:.0%} "
                        f"but is not a vendor/asset link — someone assumed this was reliable."
                    ),
                    affected_node_ids=[u, v],
                    scan_type="structural",
                    confidence=0.75,
                ))

        # 1b. High in-degree nodes with low confidence
        in_degrees = dict(self.G.in_degree())
        max_in = max(in_degrees.values(), default=1)
        for nid, data in self.G.nodes(data=True):
            conf = data.get("confidence", 1.0)
            indeg = in_degrees.get(nid, 0)
            if conf < 0.55 and indeg >= 3:
                label = data.get("label", nid)
                results.append(ImplicitAssumption(
                    description=(
                        f"'{label}' has {indeg} dependents but confidence={conf:.0%} — "
                        "many nodes rely on poorly-validated data."
                    ),
                    affected_node_ids=[nid],
                    scan_type="structural",
                    confidence=0.8,
                ))

        # 1c. Dark paths — chains where every node has visibility < 0.4
        for nid, data in self.G.nodes(data=True):
            vis = data.get("visibility", 1.0)
            if vis >= 0.4:
                continue
            # Check if all successors are also low-visibility
            succs = list(self.G.successors(nid))
            dark_succs = [s for s in succs if self.G.nodes[s].get("visibility", 1.0) < 0.4]
            if len(dark_succs) >= 2:
                label = data.get("label", nid)
                affected = [nid] + dark_succs
                results.append(ImplicitAssumption(
                    description=(
                        f"'{label}' feeds {len(dark_succs)} other low-visibility nodes — "
                        "a dark dependency chain exists that observers cannot monitor."
                    ),
                    affected_node_ids=affected,
                    scan_type="structural",
                    confidence=0.7,
                ))

        # 1d. Unbreakable contingencies
        for u, v, data in self.G.edges(data=True):
            if data.get("edge_type") != EdgeType.CONTINGENT_ON.value:
                continue
            u_node = self._node_map.get(u)
            if u_node and u_node.attributes.replaceability < 0.01:
                u_label = self.G.nodes[u].get("label", u)
                v_label = self.G.nodes[v].get("label", v)
                results.append(ImplicitAssumption(
                    description=(
                        f"'{u_label}' is contingent on '{v_label}' with replaceability=0 — "
                        "this is a hard assumption with no escape path."
                    ),
                    affected_node_ids=[u, v],
                    scan_type="structural",
                    confidence=0.9,
                ))

        # Deduplicate by description prefix
        seen: set[str] = set()
        unique = []
        for ia in results:
            key = ia.description[:50]
            if key not in seen:
                seen.add(key)
                unique.append(ia)
        return unique

    # ------------------------------------------------------------------
    # Pass 2: Textual
    # ------------------------------------------------------------------

    def _textual_pass(self, text: str) -> list[ImplicitAssumption]:
        from app.utils.doc_extract import split_sentences
        sentences = split_sentences(text)
        results: list[ImplicitAssumption] = []

        for sent in sentences:
            for pattern, description_template in _IMPLICIT_PATTERNS:
                if pattern.search(sent):
                    excerpt = sent[:120].strip()
                    results.append(ImplicitAssumption(
                        description=f"{description_template}: \"{excerpt}\"",
                        affected_node_ids=[],
                        scan_type="textual",
                        confidence=0.6,
                    ))
                    break  # one match per sentence

        return results[:30]  # cap at 30 textual assumptions

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    def scan(self, text: Optional[str] = None) -> AssumptionScanResult:
        structural = self._structural_pass()
        textual = self._textual_pass(text) if text else []
        return AssumptionScanResult(
            implicit_assumptions=structural + textual,
            structural_count=len(structural),
            textual_count=len(textual),
        )


from typing import Optional  # noqa: E402 — keep at bottom for forward ref
