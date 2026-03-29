"""Agent-based simulation API endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.crud import get_graph
from app.engines.agent_sim import AgentSimEngine
from app.auth.auth import get_optional_user

router = APIRouter(prefix="/agent-sim", tags=["agent-sim"])


class AgentSimRequest(BaseModel):
    stress_node_id: str
    n_steps: int = 8
    initial_stress: float = 0.9
    seed: Optional[int] = None


def _result_to_dict(result) -> dict:
    return {
        "n_steps": result.n_steps,
        "simulation_type": result.simulation_type,
        "initial_stress_node": result.initial_stress_node,
        "agents": result.agents,
        "steps": result.steps,
        "final_failed_nodes": result.final_failed_nodes,
        "final_stabilised_nodes": result.final_stabilised_nodes,
        "reversion_opportunities": result.reversion_opportunities,
        "cascade_contained": result.cascade_contained,
        "narrative": result.narrative,
    }


@router.post("/graphs/{graph_id}/run")
def run_agent_sim(
    graph_id: str,
    req: AgentSimRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Run an agent-based simulation on a stored graph.

    Stresses the specified node and simulates how 5 agent archetypes respond
    over N steps: risk-averse, risk-seeking, rule-following, crisis-manager,
    and opportunist.

    Returns step-by-step narrative, cascade status, and reversion opportunities.
    """
    graph_rec = get_graph(db, graph_id)
    if not graph_rec:
        raise HTTPException(status_code=404, detail="Graph not found")

    from app.models.graph import Graph as GraphModel
    graph = GraphModel.model_validate_json(graph_rec.graph_json)

    node_ids = {n.id for n in graph.nodes}
    if req.stress_node_id not in node_ids:
        raise HTTPException(
            status_code=422,
            detail=f"stress_node_id '{req.stress_node_id}' not found in graph",
        )

    n_steps = max(1, min(req.n_steps, 20))
    initial_stress = max(0.1, min(1.0, req.initial_stress))

    engine = AgentSimEngine(graph, seed=req.seed)
    result = engine.run(
        stress_node_id=req.stress_node_id,
        n_steps=n_steps,
        initial_stress=initial_stress,
    )
    return _result_to_dict(result)
