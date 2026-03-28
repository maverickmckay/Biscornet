"""
Repository functions — thin wrappers over the ORM that handle
Pydantic ↔ JSON serialisation.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import GraphRecord, AnalysisRecord
from app.models.graph import Graph, GraphAnalysis


# ---------------------------------------------------------------------------
# Graph CRUD
# ---------------------------------------------------------------------------

def save_graph(db: Session, graph: Graph) -> GraphRecord:
    record = db.query(GraphRecord).filter(GraphRecord.id == graph.id).first()
    if record:
        record.name = graph.name
        record.node_count = len(graph.nodes)
        record.edge_count = len(graph.edges)
        record.graph_json = graph.model_dump_json()
    else:
        record = GraphRecord(
            id=graph.id,
            name=graph.name,
            node_count=len(graph.nodes),
            edge_count=len(graph.edges),
            graph_json=graph.model_dump_json(),
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_graph(db: Session, graph_id: str) -> Optional[Graph]:
    record = db.query(GraphRecord).filter(GraphRecord.id == graph_id).first()
    if not record:
        return None
    return Graph.model_validate_json(record.graph_json)


def list_graphs(db: Session) -> list[dict]:
    records = db.query(
        GraphRecord.id, GraphRecord.name, GraphRecord.node_count,
        GraphRecord.edge_count, GraphRecord.created_at,
    ).all()
    return [
        {"id": r.id, "name": r.name, "nodes": r.node_count, "edges": r.edge_count}
        for r in records
    ]


def delete_graph(db: Session, graph_id: str) -> bool:
    record = db.query(GraphRecord).filter(GraphRecord.id == graph_id).first()
    if not record:
        return False
    db.delete(record)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Analysis CRUD
# ---------------------------------------------------------------------------

def save_analysis(db: Session, analysis: GraphAnalysis) -> AnalysisRecord:
    record = AnalysisRecord(
        id=str(uuid.uuid4()),
        graph_id=analysis.graph_id,
        analysis_json=analysis.model_dump_json(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_analysis(db: Session, graph_id: str) -> Optional[GraphAnalysis]:
    record = (
        db.query(AnalysisRecord)
        .filter(AnalysisRecord.graph_id == graph_id)
        .order_by(AnalysisRecord.created_at.desc())
        .first()
    )
    if not record:
        return None
    return GraphAnalysis.model_validate_json(record.analysis_json)
