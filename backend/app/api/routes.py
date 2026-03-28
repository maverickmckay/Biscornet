"""
Core API routes for No Next Move.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.crud import (
    save_graph, get_graph, list_graphs, delete_graph,
    save_analysis, get_latest_analysis,
)
from app.models.graph import Graph, GraphAnalysis
from app.engines.analyzer import analyze
from app.engines.scenario import ScenarioEngine
from app.engines.monte_carlo import MonteCarloEngine
from app.utils.ingest import from_json, from_csv_edge_list

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SimulationRequest(BaseModel):
    simulation_type: str
    node_id: str
    params: dict = {}


class MonteCarloRequest(BaseModel):
    simulation_type: str
    node_id: str
    n_trials: int = 500
    seed: Optional[int] = None
    params: dict = {}


class NodeAttributePatch(BaseModel):
    load: Optional[float] = None
    criticality: Optional[float] = None
    replaceability: Optional[float] = None
    reversibility: Optional[float] = None
    time_sensitivity: Optional[float] = None
    confidence: Optional[float] = None
    visibility: Optional[float] = None


# ---------------------------------------------------------------------------
# Graph CRUD
# ---------------------------------------------------------------------------

@router.post("/graphs", response_model=Graph, status_code=201)
async def create_graph(graph: Graph, db: Session = Depends(get_db)):
    if not graph.id:
        graph.id = str(uuid.uuid4())
    save_graph(db, graph)
    return graph


@router.post("/graphs/csv", response_model=Graph, status_code=201)
async def create_graph_from_csv(
    file: UploadFile = File(...),
    name: str = Form("Imported graph"),
    db: Session = Depends(get_db),
):
    raw = (await file.read()).decode("utf-8")
    graph = from_csv_edge_list(raw, graph_name=name)
    save_graph(db, graph)
    return graph


@router.post("/graphs/json", response_model=Graph, status_code=201)
async def create_graph_from_json(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    graph = from_json(raw)
    save_graph(db, graph)
    return graph


@router.get("/graphs", response_model=list[dict])
async def list_all_graphs(db: Session = Depends(get_db)):
    return list_graphs(db)


@router.get("/graphs/{graph_id}", response_model=Graph)
async def get_graph_route(graph_id: str, db: Session = Depends(get_db)):
    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")
    return g


@router.delete("/graphs/{graph_id}", status_code=204)
async def delete_graph_route(graph_id: str, db: Session = Depends(get_db)):
    if not delete_graph(db, graph_id):
        raise HTTPException(404, "Graph not found")


# ---------------------------------------------------------------------------
# Node attribute patch (for log calibration and manual updates)
# ---------------------------------------------------------------------------

@router.patch("/graphs/{graph_id}/nodes/{node_id}/attributes")
async def patch_node_attributes(
    graph_id: str,
    node_id: str,
    patch: NodeAttributePatch,
    db: Session = Depends(get_db),
):
    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")
    node = next((n for n in g.nodes if n.id == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")

    for field, value in patch.model_dump(exclude_none=True).items():
        setattr(node.attributes, field, value)

    save_graph(db, g)
    return {"updated": True, "node_id": node_id, "attributes": node.attributes.model_dump()}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@router.post("/graphs/{graph_id}/analyze", response_model=GraphAnalysis)
async def analyze_graph(graph_id: str, db: Session = Depends(get_db)):
    from app.api.events import broadcast
    import asyncio

    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")

    result = analyze(g)
    save_analysis(db, result)

    asyncio.create_task(broadcast("analysis_updated", {
        "graph_id": graph_id,
        "summary": result.summary,
        "trigger": "analyze",
    }))

    return result


@router.get("/graphs/{graph_id}/analyze", response_model=GraphAnalysis)
async def get_cached_analysis(graph_id: str, db: Session = Depends(get_db)):
    """Return the most recent cached analysis (does not re-run the engines)."""
    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")

    cached = get_latest_analysis(db, graph_id)
    if cached:
        return cached

    # No cache — run and store
    result = analyze(g)
    save_analysis(db, result)
    return result


# ---------------------------------------------------------------------------
# Scenario simulation
# ---------------------------------------------------------------------------

@router.post("/graphs/{graph_id}/simulate")
async def simulate(
    graph_id: str,
    req: SimulationRequest,
    db: Session = Depends(get_db),
):
    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")

    engine = ScenarioEngine(g)
    sim_type = req.simulation_type.lower()

    dispatch = {
        "node_removal":        lambda: engine.node_removal(req.node_id),
        "delay_injection":     lambda: engine.delay_injection(req.node_id, req.params.get("multiplier", 5.0)),
        "cost_shock":          lambda: engine.cost_shock(req.node_id, req.params.get("reduction", 0.5)),
        "assumption_failure":  lambda: engine.assumption_failure(req.node_id),
        "approval_blockage":   lambda: engine.approval_blockage(req.node_id),
        "vendor_outage":       lambda: engine.vendor_outage(req.node_id),
        "clause_invalidation": lambda: engine.clause_invalidation(req.node_id),
        "leadership_absence":  lambda: engine.leadership_absence(req.node_id),
        "comms_blackout":      lambda: engine.comms_blackout(
            [req.node_id] + req.params.get("additional_node_ids", [])
        ),
        "full":                lambda: [r.__dict__ for r in engine.full_node_simulation(req.node_id)],
    }

    fn = dispatch.get(sim_type)
    if fn is None:
        raise HTTPException(400, f"Unknown simulation_type: {sim_type}")

    result = fn()
    if isinstance(result, list):
        return result
    return result.__dict__


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

@router.post("/graphs/{graph_id}/monte-carlo")
async def monte_carlo(
    graph_id: str,
    req: MonteCarloRequest,
    db: Session = Depends(get_db),
):
    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")

    engine = MonteCarloEngine(g, n_trials=req.n_trials, seed=req.seed)
    result = engine.run(req.simulation_type, req.node_id, req.params)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Per-node scores
# ---------------------------------------------------------------------------

@router.get("/graphs/{graph_id}/nodes/{node_id}/scores")
async def node_scores(
    graph_id: str,
    node_id: str,
    db: Session = Depends(get_db),
):
    g = get_graph(db, graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")

    from app.engines.scoring import ScoringEngine
    from app.engines.classifier import ActionClassifier
    scoring = ScoringEngine(g)
    classifier = ActionClassifier(g, scoring)
    scores = scoring.score_node(node_id)
    action, rationale = classifier.classify_node(node_id)
    return {**scores, "action": action.value, "action_rationale": rationale}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

@router.get("/demo", response_model=GraphAnalysis)
async def demo(db: Session = Depends(get_db)):
    demo_path = Path(__file__).parent.parent.parent / "data" / "samples" / "supply_chain_demo.json"
    if not demo_path.exists():
        raise HTTPException(404, "Demo data not found")
    graph = from_json(demo_path.read_bytes())
    graph.id = "demo"
    save_graph(db, graph)
    result = analyze(graph)
    save_analysis(db, result)
    return result
