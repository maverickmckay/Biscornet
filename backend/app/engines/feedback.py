"""
Feedback / outcome recording and classifier weight tuning.

Records what action was recommended vs what outcome occurred.
Uses exponential moving average to tune NNM_WEIGHTS in the scoring engine.

Outcome types:
  resolved    — the action was taken and the problem was fixed
  worsened    — situation deteriorated (action was too weak or wrong)
  unchanged   — no change (action not taken or ineffective)
  collapsed   — full collapse occurred
  avoided     — avoided successfully (relevant for AVOID actions)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, String, Float, DateTime, Text, func
from sqlalchemy.orm import Session

from app.db.database import Base
from app.models.graph import ActionLabel


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class OutcomeRecord(Base):
    __tablename__ = "outcomes"

    id = Column(String, primary_key=True)
    graph_id = Column(String, index=True, nullable=False)
    node_id = Column(String, nullable=False)
    node_label = Column(String)
    action_taken = Column(String, nullable=False)
    outcome = Column(String, nullable=False)   # resolved|worsened|unchanged|collapsed|avoided
    nnm_score_at_time = Column(Float)
    notes = Column(Text)
    recorded_at = Column(DateTime, default=func.now())
    weight_snapshot = Column(Text)   # JSON of NNM_WEIGHTS at recording time


# ---------------------------------------------------------------------------
# Weight tuning
# ---------------------------------------------------------------------------

# Copy of base weights from scoring.py — tuned independently here
_BASE_WEIGHTS = {
    "reroute_failure":          0.35,
    "time_to_failure":          0.20,
    "dependency_concentration": 0.20,
    "return_loop_absence":      0.15,
    "hidden_constraint":        0.10,
}

# EMA smoothing factor for weight updates
_ALPHA = 0.05  # 5% update per outcome observation


@dataclass
class TuningResult:
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    update_reason: str
    n_outcomes_used: int


def _load_current_weights(db: Session) -> dict[str, float]:
    """Load the most recently saved weight snapshot, or return base weights."""
    latest = (
        db.query(OutcomeRecord)
        .filter(OutcomeRecord.weight_snapshot.isnot(None))
        .order_by(OutcomeRecord.recorded_at.desc())
        .first()
    )
    if latest and latest.weight_snapshot:
        try:
            return json.loads(latest.weight_snapshot)
        except Exception:
            pass
    return dict(_BASE_WEIGHTS)


def _ema_update(old: float, target: float, alpha: float = _ALPHA) -> float:
    return round(old * (1 - alpha) + target * alpha, 6)


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    """Ensure weights sum to 1."""
    total = sum(weights.values())
    return {k: round(v / total, 6) for k, v in weights.items()}


def tune_weights_from_outcome(
    db: Session,
    action: ActionLabel,
    outcome: str,
    nnm_score: float,
) -> TuningResult:
    """
    Update NNM weights based on one outcome observation.

    Logic:
      If action=FIX and outcome=resolved → reroute_failure was correctly high
        → reinforce reroute_failure weight
      If action=AVOID and outcome=collapsed → hidden constraints were underweighted
        → reinforce hidden_constraint weight
      If action=MONITOR and outcome=collapsed → we underweighted time_to_failure
        → reinforce time_to_failure weight
      If action=HEDGE and outcome=worsened → dependency concentration underweighted
        → reinforce dependency_concentration weight
    """
    old = _load_current_weights(db)
    new = dict(old)
    reason = f"action={action.value}, outcome={outcome}, nnm_score={nnm_score:.3f}"

    if action == ActionLabel.FIX and outcome == "resolved":
        new["reroute_failure"] = _ema_update(old["reroute_failure"], old["reroute_failure"] + 0.03)
    elif action == ActionLabel.AVOID and outcome in ("collapsed", "worsened"):
        new["hidden_constraint"] = _ema_update(old["hidden_constraint"], old["hidden_constraint"] + 0.04)
    elif action == ActionLabel.MONITOR and outcome == "collapsed":
        new["time_to_failure"] = _ema_update(old["time_to_failure"], old["time_to_failure"] + 0.04)
        new["return_loop_absence"] = _ema_update(old["return_loop_absence"], old["return_loop_absence"] + 0.02)
    elif action == ActionLabel.HEDGE and outcome == "worsened":
        new["dependency_concentration"] = _ema_update(old["dependency_concentration"], old["dependency_concentration"] + 0.03)
    elif action == ActionLabel.ESCALATE and outcome == "resolved":
        # Escalation worked — hidden constraints were correctly surfaced
        new["hidden_constraint"] = _ema_update(old["hidden_constraint"], old["hidden_constraint"] + 0.02)
    elif outcome == "unchanged":
        # No signal — mild regression toward base weights
        for k in new:
            new[k] = _ema_update(new[k], _BASE_WEIGHTS[k], alpha=0.02)

    new = _normalise(new)
    return TuningResult(old_weights=old, new_weights=new, update_reason=reason, n_outcomes_used=1)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def record_outcome(
    db: Session,
    graph_id: str,
    node_id: str,
    node_label: str,
    action_taken: str,
    outcome: str,
    nnm_score: float,
    notes: Optional[str] = None,
) -> OutcomeRecord:
    tuning = tune_weights_from_outcome(
        db,
        ActionLabel(action_taken),
        outcome,
        nnm_score,
    )
    record = OutcomeRecord(
        id=str(uuid.uuid4()),
        graph_id=graph_id,
        node_id=node_id,
        node_label=node_label,
        action_taken=action_taken,
        outcome=outcome,
        nnm_score_at_time=nnm_score,
        notes=notes,
        weight_snapshot=json.dumps(tuning.new_weights),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_current_weights(db: Session) -> dict[str, float]:
    return _load_current_weights(db)


def list_outcomes(db: Session, graph_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = db.query(OutcomeRecord)
    if graph_id:
        q = q.filter(OutcomeRecord.graph_id == graph_id)
    records = q.order_by(OutcomeRecord.recorded_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "graph_id": r.graph_id,
            "node_id": r.node_id,
            "node_label": r.node_label,
            "action_taken": r.action_taken,
            "outcome": r.outcome,
            "nnm_score_at_time": r.nnm_score_at_time,
            "notes": r.notes,
            "recorded_at": str(r.recorded_at),
        }
        for r in records
    ]
