"""
Backtest API routes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backtest.scenarios import all_scenarios
from app.backtest.runner import run_suite, run_scenario, report_to_dict

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    scenarios: list[str] | None = None  # None = run all; list of names to run subset


@router.post("/run")
def run_backtest(req: BacktestRequest = BacktestRequest()):
    """
    Run the oracle backtest suite against known-outcome scenarios.

    Optional body: { "scenarios": ["CASCADE_SPOF", "VENDOR_COLLAPSE"] }
    Omit body or pass null scenarios to run all 6 scenarios.
    """
    available = {s.name: s for s in all_scenarios()}

    if req.scenarios:
        unknown = [n for n in req.scenarios if n not in available]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario names: {unknown}. "
                       f"Available: {list(available.keys())}",
            )
        scenarios = [available[n] for n in req.scenarios]
    else:
        scenarios = list(available.values())

    try:
        report = run_suite(scenarios)
        return report_to_dict(report)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")


@router.get("/scenarios")
def list_scenarios():
    """List all available backtest scenarios."""
    return {
        "scenarios": [
            {
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
                "ground_truth": {
                    "failure_node": s.ground_truth.failure_node_label,
                    "failure_hours": s.ground_truth.failure_hours,
                    "mechanism": s.ground_truth.mechanism.value,
                    "is_stable": s.ground_truth.is_stable,
                },
            }
            for s in all_scenarios()
        ]
    }


@router.post("/run/{scenario_name}")
def run_single_scenario(scenario_name: str):
    """Run a single named scenario and return the detailed result."""
    available = {s.name: s for s in all_scenarios()}
    if scenario_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{scenario_name}' not found. "
                   f"Available: {list(available.keys())}",
        )
    try:
        result = run_scenario(available[scenario_name])
        return {
            "scenario": result.scenario_name,
            "verdict": result.verdict,
            "composite_score": round(result.composite_score, 3),
            "tags": result.tags,
            "ground_truth": {
                "node": result.actual_failure_label,
                "hours": result.actual_failure_hours,
                "mechanism": result.actual_mechanism,
                "is_stable": result.is_stable,
            },
            "oracle": {
                "predicted_node": result.oracle_predicted_label,
                "predicted_hours": round(result.oracle_predicted_hours, 1) if result.oracle_predicted_hours else None,
                "predicted_mechanism": result.oracle_predicted_mechanism,
                "confidence": round(result.oracle_confidence, 3),
                "threshold_status": result.oracle_threshold_status,
                "lead_time_hours": round(result.oracle_lead_time_hours, 1) if result.oracle_lead_time_hours else None,
                "precursor_count": result.oracle_precursor_count,
                "warning_level": round(result.oracle_warning_level, 3),
                "top3_nodes": result.oracle_top3_nodes,
            },
            "scoring": {
                "node_hit": result.node_hit,
                "timing_error_pct": round(result.timing_error * 100, 1) if result.timing_error is not None else None,
                "timing_within_20pct": result.timing_within_20pct,
                "mechanism_hit": result.mechanism_hit,
                "false_positive": result.false_positive,
            },
            "notes": result.notes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scenario run failed: {exc}")
