"""
Ingest utilities
----------------
Parse various input formats into the Graph model.

Supported:
  - CSV edge list  (source, target, edge_type, [weight], [label_source], [label_target])
  - JSON graph     (nodes[], edges[])
  - Dict / in-memory  (used by tests and demo data)
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.models.graph import (
    Graph, Node, Edge, NodeType, EdgeType,
    NodeAttributes, EdgeAttributes,
)


def _node_type(s: str) -> NodeType:
    try:
        return NodeType(s.lower().strip())
    except ValueError:
        return NodeType.FUNCTION


def _edge_type(s: str) -> EdgeType:
    try:
        return EdgeType(s.lower().strip().replace(" ", "_"))
    except ValueError:
        return EdgeType.DEPENDS_ON


def from_dict(data: dict) -> Graph:
    """Build a Graph from a raw dict matching the Graph schema."""
    return Graph.model_validate(data)


def from_json(raw: str | bytes) -> Graph:
    """Parse JSON string/bytes into a Graph."""
    data = json.loads(raw)
    return from_dict(data)


def from_csv_edge_list(
    raw: str,
    graph_name: str = "Imported graph",
) -> Graph:
    """
    Parse a CSV edge list.

    Expected columns (order matters, extra columns ignored):
      source_id, target_id, edge_type
    Optional columns (by header name):
      source_label, target_label, source_type, target_type,
      weight, reliability, latency
    """
    reader = csv.DictReader(io.StringIO(raw.strip()))
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for row in reader:
        src_id = row.get("source_id") or row.get("source") or ""
        tgt_id = row.get("target_id") or row.get("target") or ""
        if not src_id or not tgt_id:
            continue

        src_label = row.get("source_label", src_id)
        tgt_label = row.get("target_label", tgt_id)
        src_type = _node_type(row.get("source_type", "function"))
        tgt_type = _node_type(row.get("target_type", "function"))
        et = _edge_type(row.get("edge_type", "depends_on"))

        if src_id not in nodes:
            nodes[src_id] = Node(id=src_id, label=src_label, node_type=src_type)
        if tgt_id not in nodes:
            nodes[tgt_id] = Node(id=tgt_id, label=tgt_label, node_type=tgt_type)

        ea = EdgeAttributes(
            weight=float(row.get("weight", 1.0)),
            reliability=float(row.get("reliability", 1.0)),
            latency=float(row.get("latency", 0.0)),
        )
        edges.append(Edge(
            source=src_id, target=tgt_id, edge_type=et, attributes=ea,
        ))

    return Graph(name=graph_name, nodes=list(nodes.values()), edges=edges)


def from_org_chart(rows: list[dict]) -> Graph:
    """
    Accept a list of dicts with keys: id, name, reports_to (optional), role, team.
    Produces a graph of PERSON nodes with DEPENDS_ON edges (reports_to relation).
    """
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for row in rows:
        nid = str(row["id"])
        label = row.get("name", nid)
        nodes[nid] = Node(
            id=nid, label=label, node_type=NodeType.PERSON,
            attributes=NodeAttributes(
                criticality=float(row.get("criticality", 0.5)),
                replaceability=float(row.get("replaceability", 0.5)),
            ),
            tags=[row.get("role", ""), row.get("team", "")],
        )

    for row in rows:
        nid = str(row["id"])
        reports_to = row.get("reports_to")
        if reports_to:
            edges.append(Edge(
                source=nid,
                target=str(reports_to),
                edge_type=EdgeType.ESCALATES_TO,
            ))

    return Graph(name="Org Chart", nodes=list(nodes.values()), edges=edges)
