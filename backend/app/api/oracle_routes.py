"""
Oracle API — integrated forward prediction endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.crud import get_graph, get_latest_analysis
from app.telemetry.ingestor import get_history
from app.engines.oracle import OracleEngine, oracle_to_dict
from app.auth.auth import get_optional_user

router = APIRouter(prefix="/oracle", tags=["oracle"])


@router.post("/graphs/{graph_id}/predict")
def oracle_predict(
    graph_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Run the full oracle prediction for a graph.

    Integrates:
      - Causal mechanism analysis (failure chains by mechanism type)
      - Threshold proximity (timing projections from live telemetry history)
      - Precursor signatures (12 pattern types, active signature detection)
      - Structural isomorphism (analog matching against 8 failure archetypes)
      - Adversarial scenarios (max damage, surprise failures, mitigation defeats)
      - Ensemble reasoning (6 weight variants, disagreement surfacing)

    Returns:
      - Primary failure sequence with timing estimates
      - Analog archetype and historical failure rate
      - Active precursor signatures with lead times
      - Top adversarial scenarios
      - Ensemble confidence and contested predictions
      - Uncertainty decomposition (what is and isn't knowable)
    """
    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    # Load latest analysis if available
    analysis_rec = get_latest_analysis(db, graph_id)
    analysis = None
    if analysis_rec:
        try:
            from app.models.graph import GraphAnalysis
            analysis = GraphAnalysis.model_validate_json(analysis_rec.analysis_json)
        except Exception:
            analysis = None

    # Load telemetry history
    node_history = get_history(db, graph_id, limit=100)

    try:
        engine = OracleEngine(graph, analysis=analysis, node_history=node_history)
        prediction = engine.predict()
        return oracle_to_dict(prediction)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Oracle prediction failed: {exc}")


@router.get("/graphs/{graph_id}/threshold")
def threshold_proximity(
    graph_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Return threshold proximity scores for all nodes.
    Lightweight endpoint — just the timing layer without full oracle.
    """
    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    node_history = get_history(db, graph_id, limit=50)

    from app.engines.threshold import ThresholdEngine
    engine = ThresholdEngine()
    proximity = engine.score_all_nodes(graph, node_history)

    return {
        "graph_id": graph_id,
        "node_count": len(proximity),
        "proximity_scores": {
            nid: {
                "node_label": p.node_label,
                "current_load": p.current_load,
                "current_reliability": p.current_reliability,
                "current_stress": p.current_stress,
                "load_headroom": p.load_headroom,
                "load_rate_per_hour": p.load_rate_per_hour,
                "hours_to_failure": p.hours_to_failure,
                "status": p.status.value,
                "confidence": p.confidence,
                "alert_message": p.alert_message,
                "trajectory": [
                    {
                        "hours_from_now": t.hours_from_now,
                        "projected_load": t.projected_load,
                        "projected_reliability": t.projected_reliability,
                        "confidence": t.confidence,
                    }
                    for t in p.trajectory
                ],
            }
            for nid, p in proximity.items()
        },
    }


@router.get("/graphs/{graph_id}/adversarial")
def adversarial_scan(
    graph_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """Run adversarial scenario generation — find the surprises."""
    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    analysis_rec = get_latest_analysis(db, graph_id)
    analysis = None
    if analysis_rec:
        try:
            from app.models.graph import GraphAnalysis
            analysis = GraphAnalysis.model_validate_json(analysis_rec.analysis_json)
        except Exception:
            pass

    from app.engines.adversarial import AdversarialEngine
    engine = AdversarialEngine(graph, analysis)
    report = engine.run()

    return {
        "graph_id": graph_id,
        "total_scenarios": report.total_scenarios_generated,
        "most_dangerous_label": report.most_dangerous_label,
        "surprise_labels": report.surprise_labels,
        "narrative": report.narrative,
        "scenarios": [
            {
                "category": s.category.value,
                "trigger_labels": s.trigger_labels,
                "cascade_depth": s.cascade_depth,
                "affected_labels": s.affected_labels,
                "why_dangerous": s.why_dangerous,
                "why_missed": s.why_missed,
                "damage_score": s.damage_score,
                "defeat_vector": s.defeat_vector,
            }
            for s in report.scenarios
        ],
    }
