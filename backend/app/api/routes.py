"""
FastAPI routes for No Next Move.

Endpoints:
  POST /graphs                      Upload a new graph (JSON body)
  POST /graphs/csv                  Upload a CSV edge list
  GET  /graphs/{graph_id}           Retrieve stored graph
  POST /graphs/{graph_id}/analyze   Run full analysis
  POST /graphs/{graph_id}/simulate  Run specific scenario
  GET  /graphs/{graph_id}/nodes/{node_id}/scores  Per-node scores
  GET  /demo                        Load and analyze the built-in demo graph
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from app.models.graph import Graph, GraphAnalysis
from app.engines.analyzer import analyze
from app.engines.scenario import ScenarioEngine
from app.utils.ingest import from_json, from_csv_edge_list, from_dict

router = APIRouter()

# In-memory store for MVP (replace with DB in Phase 2)
_store: dict[str, Graph] = {}


# ---------------------------------------------------------------------------
# Request/response helpers
# ---------------------------------------------------------------------------

class SimulationRequest(BaseModel):
    simulation_type: str   # node_removal | delay_injection | cost_shock | vendor_outage | ...
    node_id: str
    params: dict = {}


# ---------------------------------------------------------------------------
# Graph CRUD
# ---------------------------------------------------------------------------

@router.post("/graphs", response_model=Graph, status_code=201)
async def create_graph(graph: Graph):
    if not graph.id:
        graph.id = str(uuid.uuid4())
    _store[graph.id] = graph
    return graph


@router.post("/graphs/csv", response_model=Graph, status_code=201)
async def create_graph_from_csv(
    file: UploadFile = File(...),
    name: str = Form("Imported graph"),
):
    raw = (await file.read()).decode("utf-8")
    graph = from_csv_edge_list(raw, graph_name=name)
    _store[graph.id] = graph
    return graph


@router.post("/graphs/json", response_model=Graph, status_code=201)
async def create_graph_from_json(file: UploadFile = File(...)):
    raw = await file.read()
    graph = from_json(raw)
    _store[graph.id] = graph
    return graph


@router.get("/graphs", response_model=list[dict])
async def list_graphs():
    return [{"id": g.id, "name": g.name, "nodes": len(g.nodes), "edges": len(g.edges)}
            for g in _store.values()]


@router.get("/graphs/{graph_id}", response_model=Graph)
async def get_graph(graph_id: str):
    g = _store.get(graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")
    return g


@router.delete("/graphs/{graph_id}", status_code=204)
async def delete_graph(graph_id: str):
    if graph_id not in _store:
        raise HTTPException(404, "Graph not found")
    del _store[graph_id]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@router.post("/graphs/{graph_id}/analyze", response_model=GraphAnalysis)
async def analyze_graph(graph_id: str):
    g = _store.get(graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")
    return analyze(g)


# ---------------------------------------------------------------------------
# Scenario simulation
# ---------------------------------------------------------------------------

@router.post("/graphs/{graph_id}/simulate")
async def simulate(graph_id: str, req: SimulationRequest):
    g = _store.get(graph_id)
    if not g:
        raise HTTPException(404, "Graph not found")

    engine = ScenarioEngine(g)
    sim_type = req.simulation_type.lower()

    if sim_type == "node_removal":
        result = engine.node_removal(req.node_id)
    elif sim_type == "delay_injection":
        result = engine.delay_injection(req.node_id, req.params.get("multiplier", 5.0))
    elif sim_type == "cost_shock":
        result = engine.cost_shock(req.node_id, req.params.get("reduction", 0.5))
    elif sim_type == "assumption_failure":
        result = engine.assumption_failure(req.node_id)
    elif sim_type == "approval_blockage":
        result = engine.approval_blockage(req.node_id)
    elif sim_type == "vendor_outage":
        result = engine.vendor_outage(req.node_id)
    elif sim_type == "clause_invalidation":
        result = engine.clause_invalidation(req.node_id)
    elif sim_type == "leadership_absence":
        result = engine.leadership_absence(req.node_id)
    elif sim_type == "comms_blackout":
        extra_ids = req.params.get("additional_node_ids", [])
        result = engine.comms_blackout([req.node_id] + extra_ids)
    elif sim_type == "full":
        results = engine.full_node_simulation(req.node_id)
        return [r.__dict__ for r in results]
    else:
        raise HTTPException(400, f"Unknown simulation_type: {sim_type}")

    return result.__dict__


# ---------------------------------------------------------------------------
# Per-node scores
# ---------------------------------------------------------------------------

@router.get("/graphs/{graph_id}/nodes/{node_id}/scores")
async def node_scores(graph_id: str, node_id: str):
    g = _store.get(graph_id)
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
async def demo():
    """Load the built-in supply-chain demo graph and return analysis."""
    demo_path = Path(__file__).parent.parent.parent / "data" / "samples" / "supply_chain_demo.json"
    if not demo_path.exists():
        raise HTTPException(404, "Demo data not found")
    graph = from_json(demo_path.read_bytes())
    graph.id = "demo"
    _store["demo"] = graph
    return analyze(graph)
