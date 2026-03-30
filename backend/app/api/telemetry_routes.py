"""
Telemetry API — live node state push and history retrieval.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.crud import get_graph
from app.telemetry.ingestor import push_batch, get_history, bootstrap_from_graph
from app.auth.auth import get_optional_user

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class NodeReading(BaseModel):
    node_id: str
    load: float
    reliability: float
    stress: float = 0.0
    source: str = "api"
    timestamp: Optional[str] = None


class BatchReadingRequest(BaseModel):
    readings: list[NodeReading]


@router.post("/graphs/{graph_id}/readings")
def push_readings(
    graph_id: str,
    req: BatchReadingRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Push one or more live node state readings for a graph.
    These feed the threshold proximity engine for timing predictions.
    """
    graph_rec = get_graph(db, graph_id)
    if not graph_rec:
        raise HTTPException(status_code=404, detail="Graph not found")

    records = push_batch(
        db=db,
        graph_id=graph_id,
        readings=[r.model_dump() for r in req.readings],
    )
    return {
        "graph_id": graph_id,
        "readings_stored": len(records),
        "node_ids": list({r.node_id for r in records}),
    }


@router.get("/graphs/{graph_id}/history")
def get_node_history(
    graph_id: str,
    node_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Retrieve historical readings for a graph's nodes.
    Optionally filter by node_id.
    """
    graph_rec = get_graph(db, graph_id)
    if not graph_rec:
        raise HTTPException(status_code=404, detail="Graph not found")

    history = get_history(db, graph_id, node_id=node_id, limit=limit)
    return {
        "graph_id": graph_id,
        "node_count": len(history),
        "history": {
            nid: [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "load": r.load,
                    "reliability": r.reliability,
                    "stress": r.stress,
                    "source": r.source,
                }
                for r in readings
            ]
            for nid, readings in history.items()
        },
    }


@router.post("/graphs/{graph_id}/bootstrap")
def bootstrap_history(
    graph_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Create synthetic readings from current node attributes.
    Use this when no live telemetry exists yet — gives the
    threshold engine a starting point for baseline calculations.
    """
    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    records = bootstrap_from_graph(db, graph_id, graph)
    return {
        "graph_id": graph_id,
        "bootstrapped_nodes": len(records),
        "note": "Synthetic readings created from node attributes. Push live telemetry to improve predictions.",
    }
