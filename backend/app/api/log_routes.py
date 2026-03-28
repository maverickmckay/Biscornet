"""
Workflow log ingestion API routes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db.database import get_db
from app.db.crud import get_graph, save_graph
from app.utils.log_ingest import WorkflowLogIngestor, normalise_log_csv, normalise_log_json

router = APIRouter()


@router.post("/logs/ingest")
async def ingest_log(
    file: UploadFile = File(...),
):
    """
    Analyse a workflow event log (CSV or JSON).
    Returns bottleneck labels, load calibration values, inferred edges, and stats.
    Does NOT modify any stored graph — use /logs/ingest-and-calibrate for that.
    """
    from pathlib import Path
    ext = Path(file.filename or "log.csv").suffix.lower()
    raw = (await file.read()).decode("utf-8")

    if ext == ".json":
        records = normalise_log_json(raw)
    else:
        records = normalise_log_csv(raw)

    ingestor = WorkflowLogIngestor(records)
    result = ingestor.analyse()

    return {
        "bottleneck_labels": result.bottleneck_labels,
        "load_updates": result.load_updates,
        "inferred_edges": result.inferred_edges,
        "summary_stats": result.summary_stats,
        "warnings": result.warnings,
        "activity_stats": [
            {
                "label": s.label,
                "count": s.count,
                "mean_duration_h": s.mean_duration,
                "p90_duration_h": s.p90_duration,
                "queue_depth": s.queue_depth,
                "load": s.load,
                "is_bottleneck": s.is_bottleneck,
            }
            for s in result.activity_stats[:50]
        ],
    }


@router.post("/logs/ingest-and-calibrate/{graph_id}")
async def ingest_and_calibrate(
    graph_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Ingest a log and directly calibrate node load values in the stored graph.
    Matches log activity labels to graph node labels (case-insensitive substring match).
    Re-runs analysis and returns updated GraphAnalysis.
    """
    from pathlib import Path
    from app.engines.analyzer import analyze
    from app.db.crud import save_analysis
    from app.api.events import broadcast
    import asyncio

    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(404, f"Graph {graph_id} not found")

    ext = Path(file.filename or "log.csv").suffix.lower()
    raw = (await file.read()).decode("utf-8")

    records = normalise_log_json(raw) if ext == ".json" else normalise_log_csv(raw)
    ingestor = WorkflowLogIngestor(records)
    result = ingestor.analyse()

    # Match log labels to graph nodes (case-insensitive substring)
    calibrated: list[str] = []
    for node in graph.nodes:
        node_label_lower = node.label.lower()
        for log_label, load_val in result.load_updates.items():
            if log_label.lower() in node_label_lower or node_label_lower in log_label.lower():
                node.attributes.load = load_val
                calibrated.append(node.label)
                break

    save_graph(db, graph)
    analysis = analyze(graph)
    save_analysis(db, analysis)

    # Broadcast live update
    asyncio.create_task(broadcast("analysis_updated", {
        "graph_id": graph_id,
        "summary": analysis.summary,
        "trigger": "log_calibration",
    }))

    return {
        "calibrated_nodes": calibrated,
        "bottleneck_labels": result.bottleneck_labels,
        "warnings": result.warnings,
        "analysis": analysis.model_dump(),
    }
