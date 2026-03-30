"""
Telemetry Ingestor
-------------------
Receives live state updates for graph nodes and persists them to the
NodeHistoryRecord table. These readings feed the ThresholdEngine
for timing projections.

Supports:
  - Batch push (JSON payload of node readings)
  - CSV upload (workflow-log style)
  - Synthesised readings from node attributes (bootstrap)

The ingestor is the bridge between the static NNM graph and the
dynamic threshold/oracle engines.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.engines.threshold import NodeStateReading
from app.db.history_models import NodeHistoryRecord


def push_reading(
    db: Session,
    graph_id: str,
    node_id: str,
    load: float,
    reliability: float,
    stress: float = 0.0,
    source: str = "api",
    timestamp: Optional[datetime] = None,
) -> NodeHistoryRecord:
    """Persist a single node state reading."""
    ts = timestamp or datetime.now(timezone.utc)
    record = NodeHistoryRecord(
        id=str(uuid.uuid4()),
        graph_id=graph_id,
        node_id=node_id,
        load=max(0.0, min(1.0, load)),
        reliability=max(0.0, min(1.0, reliability)),
        stress=max(0.0, min(1.0, stress)),
        source=source,
        recorded_at=ts,
    )
    db.add(record)
    db.commit()
    return record


def push_batch(
    db: Session,
    graph_id: str,
    readings: list[dict],
) -> list[NodeHistoryRecord]:
    """
    Persist a batch of readings.
    Each reading dict: {node_id, load, reliability, stress?, source?, timestamp?}
    """
    records = []
    for r in readings:
        ts_raw = r.get("timestamp")
        if isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw)
            except Exception:
                ts = datetime.now(timezone.utc)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now(timezone.utc)

        rec = push_reading(
            db=db,
            graph_id=graph_id,
            node_id=r["node_id"],
            load=float(r.get("load", 0.0)),
            reliability=float(r.get("reliability", 1.0)),
            stress=float(r.get("stress", 0.0)),
            source=r.get("source", "api"),
            timestamp=ts,
        )
        records.append(rec)
    return records


def get_history(
    db: Session,
    graph_id: str,
    node_id: Optional[str] = None,
    limit: int = 50,
) -> dict[str, list[NodeStateReading]]:
    """
    Retrieve historical readings for a graph, grouped by node_id.
    Returns: {node_id: [NodeStateReading, ...]} oldest → newest
    """
    q = db.query(NodeHistoryRecord).filter(NodeHistoryRecord.graph_id == graph_id)
    if node_id:
        q = q.filter(NodeHistoryRecord.node_id == node_id)
    q = q.order_by(NodeHistoryRecord.recorded_at.asc()).limit(limit)
    records = q.all()

    result: dict[str, list[NodeStateReading]] = {}
    for rec in records:
        if rec.node_id not in result:
            result[rec.node_id] = []
        result[rec.node_id].append(NodeStateReading(
            timestamp=rec.recorded_at,
            load=rec.load,
            reliability=rec.reliability,
            stress=rec.stress,
            source=rec.source,
        ))
    return result


def bootstrap_from_graph(
    db: Session,
    graph_id: str,
    graph,
) -> list[NodeHistoryRecord]:
    """
    Create synthetic readings from current node attributes.
    Used when no live telemetry exists yet — gives the threshold
    engine a starting point.
    """
    readings = []
    for node in graph.nodes:
        # Only bootstrap if no history exists
        existing = db.query(NodeHistoryRecord).filter(
            NodeHistoryRecord.graph_id == graph_id,
            NodeHistoryRecord.node_id == node.id,
        ).first()
        if existing:
            continue
        rec = push_reading(
            db=db,
            graph_id=graph_id,
            node_id=node.id,
            load=node.attributes.load,
            reliability=1.0 - (node.attributes.criticality * 0.1),  # approximate
            stress=node.attributes.load * node.attributes.criticality,
            source="bootstrap",
        )
        readings.append(rec)
    return readings
