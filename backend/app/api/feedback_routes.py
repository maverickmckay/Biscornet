"""Outcome feedback and classifier weight tuning endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.engines.feedback import record_outcome, get_current_weights, list_outcomes
from app.auth.auth import get_optional_user

router = APIRouter(prefix="/feedback", tags=["feedback"])

VALID_OUTCOMES = {"resolved", "worsened", "unchanged", "collapsed", "avoided"}
VALID_ACTIONS = {"fix", "monitor", "avoid", "hedge", "escalate", "stress_test", "exploit_lawful"}


class OutcomeRequest(BaseModel):
    graph_id: str
    node_id: str
    node_label: str
    action_taken: str
    outcome: str
    nnm_score: float
    notes: Optional[str] = None


@router.post("/outcomes")
def submit_outcome(
    req: OutcomeRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Record the real-world outcome of a recommended action.
    Updates NNM_WEIGHTS via EMA based on what worked (or didn't).
    """
    if req.outcome not in VALID_OUTCOMES:
        raise HTTPException(
            status_code=422,
            detail=f"outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}",
        )
    if req.action_taken not in VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"action_taken must be one of: {', '.join(sorted(VALID_ACTIONS))}",
        )

    rec = record_outcome(
        db=db,
        graph_id=req.graph_id,
        node_id=req.node_id,
        node_label=req.node_label,
        action_taken=req.action_taken,
        outcome=req.outcome,
        nnm_score=req.nnm_score,
        notes=req.notes,
    )
    weights = get_current_weights(db)
    return {
        "id": rec.id,
        "recorded_at": str(rec.recorded_at),
        "current_weights": weights,
    }


@router.get("/weights")
def current_weights(
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """Return the current NNM scoring weights (base or EMA-adjusted)."""
    return {"weights": get_current_weights(db)}


@router.get("/outcomes")
def get_outcomes(
    graph_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """List recorded outcomes, optionally filtered by graph_id."""
    return {"outcomes": list_outcomes(db, graph_id=graph_id, limit=limit)}
