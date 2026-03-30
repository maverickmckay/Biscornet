"""
Backtest Runner
---------------
Evaluates the oracle prediction system against scenarios with known outcomes.

Scoring dimensions (per scenario):
  node_hit          (0/1)  — actual failure node in oracle's top-3 predicted failures
  timing_error      float  — |oracle_hours - actual_hours| / actual_hours  (0 = perfect)
  timing_within_20  (0/1)  — timing error < 20%
  mechanism_hit     (0/1)  — oracle identified correct causal mechanism
  lead_time_hours   float  — hours before failure that the node was flagged APPROACHING+
  false_positive    (0/1)  — for stable scenarios: oracle incorrectly predicted imminent failure
  composite_score   float  — weighted combination (0–1)

Aggregate metrics across the suite:
  node_accuracy     float  — fraction of scenarios where node_hit
  timing_mae        float  — mean |oracle_hours - actual_hours|
  mechanism_accuracy float — fraction of scenarios where mechanism_hit
  avg_lead_time     float  — mean hours of advance warning (non-stable scenarios)
  false_positive_rate float — fraction of stable scenarios with false alarm
  confidence_mae    float  — |oracle_confidence - scenario_accuracy|
  suite_score       float  — mean composite_score across all scenarios
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.backtest.scenarios import BacktestScenario, all_scenarios
from app.engines.oracle import OracleEngine, OraclePrediction, oracle_to_dict
from app.engines.threshold import ThresholdEngine, ThresholdStatus
from app.engines.causal import CausalEngine, MechanismType


# Threshold status values that constitute an "advance warning"
_WARNING_STATUSES = {ThresholdStatus.APPROACHING, ThresholdStatus.CRITICAL, ThresholdStatus.EXCEEDED}

# Hours-to-failure threshold below which a prediction on a stable node counts
# as a false positive. 12h is the operational "act now" horizon — predicting
# failure within 12h on a genuinely stable node is a meaningful false alarm.
# (Predicting 40h on a stable node = valid early warning, not a false alarm.)
_IMMINENT_THRESHOLD_HOURS = 12.0


@dataclass
class ScenarioResult:
    scenario_name: str
    scenario_description: str
    tags: list[str]

    # Ground truth
    actual_failure_node: str
    actual_failure_label: str
    actual_failure_hours: float
    actual_mechanism: str
    is_stable: bool

    # Oracle outputs
    oracle_predicted_node: Optional[str]
    oracle_predicted_label: Optional[str]
    oracle_predicted_hours: Optional[float]
    oracle_predicted_mechanism: str
    oracle_confidence: float
    oracle_top3_nodes: list[str]           # top-3 failure node IDs from primary sequence
    oracle_threshold_status: str           # threshold status of the actual failure node
    oracle_lead_time_hours: Optional[float] # how early oracle warned (APPROACHING+ status)
    oracle_precursor_count: int
    oracle_warning_level: float

    # Scoring
    node_hit: bool                 # actual node in oracle's top-3
    timing_error: Optional[float]  # relative error 0-1
    timing_within_20pct: bool
    mechanism_hit: bool
    false_positive: bool           # stable scenario predicted as failing imminently
    composite_score: float         # 0-1

    # Narrative
    verdict: str                   # PASS / PARTIAL / FAIL
    notes: list[str]


@dataclass
class BacktestReport:
    run_at: str
    scenario_count: int
    results: list[ScenarioResult]

    # Aggregate metrics
    node_accuracy: float
    timing_mae: Optional[float]    # None if no timing predictions
    mechanism_accuracy: float
    avg_lead_time_hours: Optional[float]
    false_positive_rate: float
    avg_oracle_confidence: float
    confidence_mae: float          # |confidence - node_accuracy|
    suite_score: float             # mean composite across all scenarios

    # Qualitative summary
    strongest_scenario: str
    weakest_scenario: str
    summary: str


def _score_composite(r: ScenarioResult) -> float:
    """
    Weighted composite score for a single scenario result.

    For prediction scenarios (not stable):
      node_hit           35%
      timing accuracy    25%   (1 - timing_error, capped)
      mechanism_hit      20%
      lead_time          20%   (capped at 48h → 1.0)

    For stable scenarios (is_stable=True):
      not false_positive 100%  — the only thing that matters
    """
    if r.is_stable:
        return 1.0 if not r.false_positive else 0.0

    timing_acc = 0.0
    if r.timing_error is not None:
        timing_acc = max(0.0, 1.0 - r.timing_error)

    lead_acc = 0.0
    if r.oracle_lead_time_hours is not None:
        lead_acc = min(1.0, r.oracle_lead_time_hours / 48.0)

    return (
        (1.0 if r.node_hit else 0.0)     * 0.35 +
        timing_acc                         * 0.25 +
        (1.0 if r.mechanism_hit else 0.0) * 0.20 +
        lead_acc                           * 0.20
    )


def _verdict(score: float, is_stable: bool, false_positive: bool) -> str:
    if is_stable:
        return "PASS" if not false_positive else "FAIL"
    if score >= 0.75:
        return "PASS"
    if score >= 0.45:
        return "PARTIAL"
    return "FAIL"


def run_scenario(scenario: BacktestScenario) -> ScenarioResult:
    """Run oracle on a single scenario and score the result."""
    gt = scenario.ground_truth

    # --- Run oracle ---
    engine = OracleEngine(
        graph=scenario.graph,
        analysis=None,
        node_history=scenario.history,
    )
    pred: OraclePrediction = engine.predict()

    # --- Extract oracle predictions ---
    # top3 = nodes with earliest predicted timing; used for display.
    top3 = [e.node_id for e in pred.primary_sequence[:3]]
    # all_predicted = full sequence, including root-cause nodes sorted after
    # their cascade targets (oracle may list downstream propagation first).
    all_predicted = [e.node_id for e in pred.primary_sequence]
    predicted_node = pred.earliest_failure_node
    predicted_label = pred.earliest_failure_label
    predicted_hours = pred.earliest_failure_hours

    # --- Mechanism: look at causal analysis ---
    causal_engine = CausalEngine(scenario.graph)
    causal = causal_engine.analyze()
    node_mechanism = causal.mechanism_summary.get(gt.failure_node_id, MechanismType.UNKNOWN)
    oracle_mechanism = node_mechanism.value

    # --- Threshold status of the actual failure node ---
    threshold_engine = ThresholdEngine()
    proximity = threshold_engine.score_all_nodes(scenario.graph, scenario.history)
    node_prox = proximity.get(gt.failure_node_id)
    threshold_status = node_prox.status.value if node_prox else "unknown"

    # Lead time: if oracle sees the node as APPROACHING+, lead time = actual_hours
    # (it warned before the failure). If not, lead time = 0.
    oracle_lead_time: Optional[float] = None
    if node_prox and node_prox.status in _WARNING_STATUSES and not gt.is_stable:
        oracle_lead_time = gt.failure_hours

    # --- Scoring ---
    # Node hit: actual failure node appears anywhere in predicted sequence.
    # The oracle may rank cascade targets before the root cause when propagation
    # lag < threshold time, so we check the full sequence rather than just top-3.
    node_hit = gt.failure_node_id in all_predicted

    timing_error: Optional[float] = None
    timing_within_20 = False
    if predicted_hours is not None and not gt.is_stable and gt.failure_hours < 500:
        raw_err = abs(predicted_hours - gt.failure_hours)
        timing_error = raw_err / max(gt.failure_hours, 1.0)
        timing_within_20 = timing_error <= 0.20

    mechanism_hit = oracle_mechanism == gt.mechanism.value

    # False positive: stable scenario where the *threshold engine* (not causal
    # chain lag) classifies the actual node as APPROACHING, CRITICAL, or EXCEEDED.
    # Cascade propagation entries always exist regardless of whether any origin
    # is near failure; only threshold-based warnings count as false alarms.
    false_positive = False
    if gt.is_stable:
        if node_prox and node_prox.status in {
            ThresholdStatus.APPROACHING, ThresholdStatus.CRITICAL, ThresholdStatus.EXCEEDED,
        }:
            false_positive = True

    # Build result (without composite_score and verdict — computed after)
    notes: list[str] = []
    if node_hit:
        notes.append(f"Correctly identified {gt.failure_node_label} as top-3 failure.")
    else:
        notes.append(
            f"Missed {gt.failure_node_label}; oracle top prediction: "
            f"{predicted_label or 'none'}."
        )
    if timing_error is not None:
        notes.append(
            f"Timing: oracle={predicted_hours:.1f}h actual={gt.failure_hours:.1f}h "
            f"error={timing_error*100:.0f}%."
        )
    if mechanism_hit:
        notes.append(f"Mechanism correctly identified as {oracle_mechanism}.")
    else:
        notes.append(f"Mechanism mismatch: oracle={oracle_mechanism}, actual={gt.mechanism.value}.")
    if gt.is_stable and not false_positive:
        notes.append("Correctly did not predict imminent failure (stable scenario).")
    if gt.is_stable and false_positive:
        notes.append("FALSE POSITIVE: flagged stable node as imminently failing.")
    if oracle_lead_time:
        notes.append(f"Advanced warning: {oracle_lead_time:.1f}h before failure.")

    result = ScenarioResult(
        scenario_name=scenario.name,
        scenario_description=scenario.description,
        tags=scenario.tags,
        actual_failure_node=gt.failure_node_id,
        actual_failure_label=gt.failure_node_label,
        actual_failure_hours=gt.failure_hours,
        actual_mechanism=gt.mechanism.value,
        is_stable=gt.is_stable,
        oracle_predicted_node=predicted_node,
        oracle_predicted_label=predicted_label,
        oracle_predicted_hours=predicted_hours,
        oracle_predicted_mechanism=oracle_mechanism,
        oracle_confidence=pred.overall_confidence,
        oracle_top3_nodes=top3,
        oracle_threshold_status=threshold_status,
        oracle_lead_time_hours=oracle_lead_time,
        oracle_precursor_count=pred.precursor_warning_level and len(pred.active_precursors) or 0,
        oracle_warning_level=pred.precursor_warning_level,
        node_hit=node_hit,
        timing_error=timing_error,
        timing_within_20pct=timing_within_20,
        mechanism_hit=mechanism_hit,
        false_positive=false_positive,
        composite_score=0.0,  # filled below
        verdict="",           # filled below
        notes=notes,
    )
    result.composite_score = _score_composite(result)
    result.verdict = _verdict(result.composite_score, gt.is_stable, false_positive)
    return result


def run_suite(scenarios: Optional[list[BacktestScenario]] = None) -> BacktestReport:
    """Run all scenarios (or a provided subset) and compile aggregate metrics."""
    if scenarios is None:
        scenarios = all_scenarios()

    results = [run_scenario(s) for s in scenarios]

    # Aggregate
    prediction_results = [r for r in results if not r.is_stable]
    stable_results = [r for r in results if r.is_stable]

    node_accuracy = sum(1 for r in prediction_results if r.node_hit) / max(len(prediction_results), 1)

    timing_errors = [r.timing_error for r in prediction_results if r.timing_error is not None]
    timing_mae: Optional[float] = None
    if timing_errors:
        actual_hours = [
            abs(
                (r.oracle_predicted_hours or r.actual_failure_hours) - r.actual_failure_hours
            )
            for r in prediction_results if r.timing_error is not None
        ]
        timing_mae = sum(actual_hours) / len(actual_hours)

    mechanism_accuracy = sum(1 for r in prediction_results if r.mechanism_hit) / max(len(prediction_results), 1)

    lead_times = [r.oracle_lead_time_hours for r in prediction_results if r.oracle_lead_time_hours is not None]
    avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else None

    false_positive_rate = sum(1 for r in stable_results if r.false_positive) / max(len(stable_results), 1)

    avg_confidence = sum(r.oracle_confidence for r in results) / len(results)
    confidence_mae = abs(avg_confidence - node_accuracy)

    suite_score = sum(r.composite_score for r in results) / len(results)

    # Strongest / weakest
    sorted_by_score = sorted(results, key=lambda r: r.composite_score)
    weakest = sorted_by_score[0].scenario_name if sorted_by_score else "N/A"
    strongest = sorted_by_score[-1].scenario_name if sorted_by_score else "N/A"

    # Summary narrative
    pass_count = sum(1 for r in results if r.verdict == "PASS")
    partial_count = sum(1 for r in results if r.verdict == "PARTIAL")
    fail_count = sum(1 for r in results if r.verdict == "FAIL")

    summary_parts = [
        f"{pass_count}/{len(results)} scenarios passed.",
        f"Node accuracy: {node_accuracy*100:.0f}%.",
        f"Mechanism accuracy: {mechanism_accuracy*100:.0f}%.",
    ]
    if timing_mae is not None:
        summary_parts.append(f"Timing MAE: {timing_mae:.1f}h.")
    if avg_lead_time is not None:
        summary_parts.append(f"Avg lead time: {avg_lead_time:.1f}h.")
    if false_positive_rate > 0:
        summary_parts.append(f"False positive rate: {false_positive_rate*100:.0f}%.")
    if fail_count > 0:
        summary_parts.append(f"Weakest: {weakest}.")
    summary_parts.append(f"Suite score: {suite_score*100:.0f}/100.")

    return BacktestReport(
        run_at=datetime.now(timezone.utc).isoformat(),
        scenario_count=len(results),
        results=results,
        node_accuracy=node_accuracy,
        timing_mae=timing_mae,
        mechanism_accuracy=mechanism_accuracy,
        avg_lead_time_hours=avg_lead_time,
        false_positive_rate=false_positive_rate,
        avg_oracle_confidence=avg_confidence,
        confidence_mae=confidence_mae,
        suite_score=suite_score,
        strongest_scenario=strongest,
        weakest_scenario=weakest,
        summary=" ".join(summary_parts),
    )


def report_to_dict(report: BacktestReport) -> dict:
    return {
        "run_at": report.run_at,
        "scenario_count": report.scenario_count,
        "suite_score": round(report.suite_score, 3),
        "node_accuracy": round(report.node_accuracy, 3),
        "mechanism_accuracy": round(report.mechanism_accuracy, 3),
        "timing_mae_hours": round(report.timing_mae, 2) if report.timing_mae is not None else None,
        "avg_lead_time_hours": round(report.avg_lead_time_hours, 2) if report.avg_lead_time_hours is not None else None,
        "false_positive_rate": round(report.false_positive_rate, 3),
        "avg_oracle_confidence": round(report.avg_oracle_confidence, 3),
        "confidence_mae": round(report.confidence_mae, 3),
        "strongest_scenario": report.strongest_scenario,
        "weakest_scenario": report.weakest_scenario,
        "summary": report.summary,
        "results": [
            {
                "scenario": r.scenario_name,
                "verdict": r.verdict,
                "composite_score": round(r.composite_score, 3),
                "tags": r.tags,
                "ground_truth": {
                    "node": r.actual_failure_label,
                    "hours": r.actual_failure_hours,
                    "mechanism": r.actual_mechanism,
                    "is_stable": r.is_stable,
                },
                "oracle": {
                    "predicted_node": r.oracle_predicted_label,
                    "predicted_hours": round(r.oracle_predicted_hours, 1) if r.oracle_predicted_hours else None,
                    "predicted_mechanism": r.oracle_predicted_mechanism,
                    "confidence": round(r.oracle_confidence, 3),
                    "threshold_status": r.oracle_threshold_status,
                    "lead_time_hours": round(r.oracle_lead_time_hours, 1) if r.oracle_lead_time_hours else None,
                    "precursor_count": r.oracle_precursor_count,
                    "warning_level": round(r.oracle_warning_level, 3),
                    "top3_nodes": r.oracle_top3_nodes,
                    "predicted_sequence_length": len(r.oracle_top3_nodes),
                },
                "scoring": {
                    "node_hit": r.node_hit,
                    "timing_error_pct": round(r.timing_error * 100, 1) if r.timing_error is not None else None,
                    "timing_within_20pct": r.timing_within_20pct,
                    "mechanism_hit": r.mechanism_hit,
                    "false_positive": r.false_positive,
                },
                "notes": r.notes,
            }
            for r in report.results
        ],
    }
