"""
Oracle Engine
--------------
Integrates all Phase 4 intelligence layers into a single, structured
forward prediction.

Components integrated:
  CausalEngine       — mechanism-based failure chain tracing
  ThresholdEngine    — timing projections from live state history
  PrecursorLibrary   — active precursor signatures
  IsomorphismEngine  — structural analog matching
  AdversarialEngine  — surprise scenario generation
  EnsembleEngine     — multi-variant confidence quantification

Output: OraclePrediction — the highest-confidence view of what fails,
in what order, in approximately what timeframe, for what reason,
and what conventional analysis would miss.

The oracle does not eliminate uncertainty. It makes uncertainty legible:
  - Here is what we know with high confidence
  - Here is what we know with moderate confidence
  - Here is what remains genuinely unknowable and why
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.models.graph import Graph, GraphAnalysis
from app.engines.causal import CausalEngine, CausalChain
from app.engines.threshold import ThresholdEngine, ProximityScore, NodeStateReading, ThresholdStatus
from app.engines.precursor import scan_precursors, PrecursorReport, SignatureMatch
from app.engines.isomorphism import IsomorphismEngine, IsomorphismResult
from app.engines.adversarial import AdversarialEngine, AdversarialReport
from app.engines.ensemble import EnsembleEngine, EnsembleResult
from app.engines.analyzer import analyze


@dataclass
class FailureEvent:
    """A predicted failure in the sequence."""
    node_id: str
    node_label: str
    estimated_hours_to_failure: Optional[float]  # None = unknown timing
    timing_confidence: float      # 0-1
    failure_mechanism: str
    trigger_type: str             # "threshold" | "cascade" | "precursor" | "adversarial"
    cascade_depth: int
    supporting_evidence: list[str]


@dataclass
class UncertaintyDecomposition:
    """Honest breakdown of what is known and unknown."""
    graph_completeness: float      # 0-1, how complete the input graph is estimated to be
    timing_confidence: float       # overall timing confidence
    mechanism_confidence: float    # causal mechanism confidence
    novel_situation_risk: float    # how much of this situation has no analog
    irreducible_unknowns: list[str]  # what genuinely cannot be predicted


@dataclass
class OraclePrediction:
    graph_id: str
    generated_at: str

    # Primary failure sequence (most likely, ordered by estimated timing)
    primary_sequence: list[FailureEvent]

    # Timing summary
    earliest_failure_hours: Optional[float]
    earliest_failure_node: Optional[str]
    earliest_failure_label: Optional[str]

    # Active precursors
    active_precursors: list[SignatureMatch]
    precursor_warning_level: float

    # Structural analog
    analog_archetype: str
    analog_failure_rate: float
    analog_narrative: str

    # Adversarial surprises
    top_adversarial_scenarios: list[dict]
    mitigation_gaps: list[str]

    # Ensemble confidence
    ensemble_confidence: float
    robust_nodes: list[str]         # nodes all variants agree on
    contested_nodes: list[str]      # nodes where variants disagree
    hidden_nodes: list[str]         # nodes base analysis misses

    # Causal mechanisms
    dominant_failure_mode: str
    highest_strength_chain: Optional[dict]

    # Uncertainty
    uncertainty: UncertaintyDecomposition

    # Overall oracle confidence
    overall_confidence: float

    # Plain-language summary
    narrative: str


class OracleEngine:
    """
    Integrates all intelligence layers into a structured forward prediction.
    """

    def __init__(
        self,
        graph: Graph,
        analysis: Optional[GraphAnalysis] = None,
        node_history: Optional[dict[str, list[NodeStateReading]]] = None,
    ):
        self.graph = graph
        self.analysis = analysis or analyze(graph)
        self.node_history = node_history or {}
        self._label_map = {n.id: n.label for n in graph.nodes}

    def predict(self) -> OraclePrediction:
        """Run all engines and produce the integrated oracle prediction."""

        # 1. Threshold proximity (timing)
        threshold_engine = ThresholdEngine()
        all_proximity: dict[str, ProximityScore] = threshold_engine.score_all_nodes(
            self.graph, self.node_history
        )

        # 2. Precursor scan
        precursor_report: PrecursorReport = scan_precursors(
            self.graph, self.node_history, all_proximity
        )

        # 3. Causal analysis
        causal_engine = CausalEngine(self.graph)
        causal_analysis = causal_engine.analyze()

        # 4. Structural isomorphism
        iso_engine = IsomorphismEngine(self.graph)
        iso_result: IsomorphismResult = iso_engine.analyze()

        # 5. Adversarial scenarios
        adversarial_engine = AdversarialEngine(self.graph, self.analysis)
        adversarial_report: AdversarialReport = adversarial_engine.run()

        # 6. Ensemble reasoning
        ensemble_engine = EnsembleEngine(self.graph)
        ensemble_result: EnsembleResult = ensemble_engine.run()

        # ── Build primary failure sequence ──────────────────────────────────
        primary_sequence = self._build_failure_sequence(
            all_proximity, precursor_report, causal_analysis, ensemble_result
        )

        # ── Timing summary ──────────────────────────────────────────────────
        timed_events = [e for e in primary_sequence if e.estimated_hours_to_failure is not None]
        if timed_events:
            earliest = min(timed_events, key=lambda e: e.estimated_hours_to_failure)
            earliest_hours = earliest.estimated_hours_to_failure
            earliest_node = earliest.node_id
            earliest_label = earliest.node_label
        else:
            earliest_hours = None
            earliest_node = None
            earliest_label = None

        # ── Adversarial scenarios (serialise top 3) ────────────────────────
        top_adversarial = [
            {
                "category": s.category.value,
                "trigger_labels": s.trigger_labels,
                "cascade_depth": s.cascade_depth,
                "why_dangerous": s.why_dangerous,
                "why_missed": s.why_missed,
                "damage_score": s.damage_score,
            }
            for s in adversarial_report.scenarios[:3]
        ]

        mitigation_gaps = [
            s.defeat_vector for s in adversarial_report.scenarios
            if s.defeat_vector
        ]

        # ── Causal dominant failure mode ────────────────────────────────────
        if causal_analysis.highest_strength_paths:
            best_chain = causal_analysis.highest_strength_paths[0]
            dominant_failure_mode = best_chain.failure_mode
            chain_dict = {
                "origin": best_chain.origin_node,
                "origin_label": self._label_map.get(best_chain.origin_node, best_chain.origin_node),
                "chain_labels": [self._label_map.get(n, n) for n in best_chain.chain],
                "cumulative_lag_hours": best_chain.cumulative_lag_hours,
                "failure_mode": best_chain.failure_mode,
                "confidence": best_chain.confidence,
            }
        else:
            dominant_failure_mode = "dependency cascade"
            chain_dict = None

        # ── Uncertainty decomposition ───────────────────────────────────────
        uncertainty = self._build_uncertainty(
            iso_result, ensemble_result, all_proximity
        )

        # ── Overall confidence ──────────────────────────────────────────────
        overall_confidence = self._compute_overall_confidence(
            ensemble_result.ensemble_confidence,
            precursor_report.composite_warning_level,
            iso_result.confidence,
            uncertainty,
        )

        # ── Narrative ──────────────────────────────────────────────────────
        narrative = self._build_narrative(
            primary_sequence, precursor_report, iso_result,
            adversarial_report, ensemble_result, earliest_hours, earliest_label,
            overall_confidence,
        )

        return OraclePrediction(
            graph_id=self.graph.id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            primary_sequence=primary_sequence,
            earliest_failure_hours=earliest_hours,
            earliest_failure_node=earliest_node,
            earliest_failure_label=earliest_label,
            active_precursors=precursor_report.active_signatures[:8],
            precursor_warning_level=precursor_report.composite_warning_level,
            analog_archetype=iso_result.best_match.archetype_name if iso_result.best_match else "UNKNOWN",
            analog_failure_rate=iso_result.best_match.historical_failure_rate if iso_result.best_match else 0.0,
            analog_narrative=iso_result.outcome_transfer,
            top_adversarial_scenarios=top_adversarial,
            mitigation_gaps=mitigation_gaps,
            ensemble_confidence=ensemble_result.ensemble_confidence,
            robust_nodes=ensemble_result.robust_predictions,
            contested_nodes=ensemble_result.contested_predictions,
            hidden_nodes=ensemble_result.hidden_by_base,
            dominant_failure_mode=dominant_failure_mode,
            highest_strength_chain=chain_dict,
            uncertainty=uncertainty,
            overall_confidence=overall_confidence,
            narrative=narrative,
        )

    def _build_failure_sequence(
        self,
        proximity: dict[str, ProximityScore],
        precursors: PrecursorReport,
        causal,
        ensemble: EnsembleResult,
    ) -> list[FailureEvent]:
        """Build ordered list of predicted failures by confidence and timing."""
        events: dict[str, FailureEvent] = {}

        # From threshold proximity
        for nid, score in proximity.items():
            if score.status in (ThresholdStatus.CRITICAL, ThresholdStatus.EXCEEDED, ThresholdStatus.APPROACHING):
                evidence = [f"Status: {score.status.value}", f"Load: {score.current_load:.2f}"]
                if score.alert_message:
                    evidence.append(score.alert_message)
                events[nid] = FailureEvent(
                    node_id=nid,
                    node_label=score.node_label,
                    estimated_hours_to_failure=score.hours_to_failure,
                    timing_confidence=score.confidence,
                    failure_mechanism="threshold_breach",
                    trigger_type="threshold",
                    cascade_depth=0,
                    supporting_evidence=evidence,
                )

        # From precursor signatures
        for sig in precursors.active_signatures:
            if sig.severity in ("critical", "high"):
                nid = sig.node_id
                if nid not in events:
                    events[nid] = FailureEvent(
                        node_id=nid,
                        node_label=sig.node_label,
                        estimated_hours_to_failure=sig.lead_time_hours,
                        timing_confidence=sig.confidence * 0.7,
                        failure_mechanism=sig.failure_mode,
                        trigger_type="precursor",
                        cascade_depth=0,
                        supporting_evidence=sig.evidence,
                    )
                else:
                    events[nid].supporting_evidence.extend(sig.evidence[:2])

        # From causal chains (top chains contribute to the sequence)
        for chain in causal.highest_strength_paths[:5]:
            for nid in chain.chain:
                if nid not in events:
                    events[nid] = FailureEvent(
                        node_id=nid,
                        node_label=self._label_map.get(nid, nid),
                        estimated_hours_to_failure=chain.cumulative_lag_hours or None,
                        timing_confidence=chain.confidence * 0.6,
                        failure_mechanism=chain.failure_mode,
                        trigger_type="cascade",
                        cascade_depth=len(chain.chain),
                        supporting_evidence=[f"Causal chain: {chain.failure_mode}", f"Strength: {chain.cumulative_strength:.2f}"],
                    )

        # From ensemble (nodes consistently flagged by all variants)
        for nid in ensemble.robust_predictions:
            if nid not in events:
                label = self._label_map.get(nid, nid)
                events[nid] = FailureEvent(
                    node_id=nid,
                    node_label=label,
                    estimated_hours_to_failure=None,
                    timing_confidence=ensemble.ensemble_confidence * 0.5,
                    failure_mechanism="structural fragility",
                    trigger_type="ensemble",
                    cascade_depth=0,
                    supporting_evidence=["All weight variants flag this node as high risk."],
                )

        # Sort: timed first (by hours), then untimed (by timing_confidence)
        timed = sorted(
            [e for e in events.values() if e.estimated_hours_to_failure is not None],
            key=lambda e: e.estimated_hours_to_failure,
        )
        untimed = sorted(
            [e for e in events.values() if e.estimated_hours_to_failure is None],
            key=lambda e: -e.timing_confidence,
        )
        return timed + untimed

    def _build_uncertainty(
        self,
        iso: IsomorphismResult,
        ensemble: EnsembleResult,
        proximity: dict[str, ProximityScore],
    ) -> UncertaintyDecomposition:
        # Graph completeness heuristic: assumption density + dark paths
        assumption_nodes = sum(
            1 for n in self.graph.nodes
            if n.attributes.visibility < 0.4 or n.attributes.confidence < 0.5
        )
        graph_completeness = max(0.0, 1.0 - (assumption_nodes / max(len(self.graph.nodes), 1)) * 1.5)

        # Timing confidence: mean of proximity confidences
        prox_confs = [p.confidence for p in proximity.values()]
        timing_confidence = sum(prox_confs) / len(prox_confs) if prox_confs else 0.3

        # Mechanism confidence: from causal engine similarity
        mechanism_confidence = iso.confidence

        # Novel situation risk: how much is NOT covered by analogs
        novel_risk = 1.0 - iso.best_match.similarity_score if iso.best_match else 0.8

        irreducibles = [
            "Timing of external shocks (regulatory, market, personnel decisions)",
            "Individual human decisions under pressure",
        ]
        if novel_risk > 0.5:
            irreducibles.append("Novel structural configuration — limited historical analog")
        if len(ensemble.contested_predictions) > len(ensemble.robust_predictions):
            irreducibles.append("High disagreement across weight variants — outcome depends on which dimensions are actually active")

        return UncertaintyDecomposition(
            graph_completeness=round(max(0.1, graph_completeness), 3),
            timing_confidence=round(timing_confidence, 3),
            mechanism_confidence=round(mechanism_confidence, 3),
            novel_situation_risk=round(novel_risk, 3),
            irreducible_unknowns=irreducibles,
        )

    def _compute_overall_confidence(
        self,
        ensemble_conf: float,
        precursor_level: float,
        iso_conf: float,
        uncertainty: UncertaintyDecomposition,
    ) -> float:
        """
        Weighted aggregate confidence in the oracle prediction.
        Higher = more confident; but never 1.0 (irreducible uncertainty always exists).
        """
        raw = (
            ensemble_conf * 0.35 +
            iso_conf * 0.25 +
            uncertainty.graph_completeness * 0.20 +
            uncertainty.timing_confidence * 0.20
        )
        # Reduce confidence if novel situation or high uncertainty
        novelty_penalty = uncertainty.novel_situation_risk * 0.15
        return round(max(0.10, min(0.92, raw - novelty_penalty)), 4)

    def _build_narrative(
        self,
        sequence: list[FailureEvent],
        precursors: PrecursorReport,
        iso: IsomorphismResult,
        adversarial: AdversarialReport,
        ensemble: EnsembleResult,
        earliest_hours: Optional[float],
        earliest_label: Optional[str],
        confidence: float,
    ) -> str:
        parts = [f"Oracle prediction (confidence: {confidence:.0%})."]

        if sequence:
            n_predicted = len(sequence)
            parts.append(f"{n_predicted} failure event(s) predicted in sequence.")

        if earliest_hours is not None and earliest_label:
            parts.append(
                f"Earliest predicted failure: '{earliest_label}' in approximately {earliest_hours:.0f} hours."
            )
        elif earliest_label:
            parts.append(f"Highest-risk node: '{earliest_label}' (timing unknown — insufficient history).")

        if precursors.total_active > 0:
            parts.append(
                f"{precursors.total_active} precursor signature(s) active (highest severity: {precursors.highest_severity})."
            )

        if iso.best_match:
            parts.append(
                f"Structural analog: {iso.best_match.archetype_name} — "
                f"historically fails {iso.best_match.historical_failure_rate:.0%} of the time."
            )

        if adversarial.scenarios:
            parts.append(f"Top adversarial risk: {adversarial.worst_scenario.why_dangerous}")

        if ensemble.ensemble_confidence < 0.5:
            parts.append(
                "WARNING: Low ensemble agreement — predictions should be treated as directional, not definitive."
            )

        return " ".join(parts)


def oracle_to_dict(pred: OraclePrediction) -> dict:
    """Serialise OraclePrediction to a JSON-compatible dict."""
    return {
        "graph_id": pred.graph_id,
        "generated_at": pred.generated_at,
        "overall_confidence": pred.overall_confidence,
        "narrative": pred.narrative,
        "primary_sequence": [
            {
                "node_id": e.node_id,
                "node_label": e.node_label,
                "estimated_hours_to_failure": e.estimated_hours_to_failure,
                "timing_confidence": e.timing_confidence,
                "failure_mechanism": e.failure_mechanism,
                "trigger_type": e.trigger_type,
                "cascade_depth": e.cascade_depth,
                "supporting_evidence": e.supporting_evidence,
            }
            for e in pred.primary_sequence
        ],
        "earliest_failure_hours": pred.earliest_failure_hours,
        "earliest_failure_node": pred.earliest_failure_node,
        "earliest_failure_label": pred.earliest_failure_label,
        "active_precursors": [
            {
                "signature": m.signature.value,
                "node_id": m.node_id,
                "node_label": m.node_label,
                "confidence": m.confidence,
                "lead_time_hours": m.lead_time_hours,
                "failure_mode": m.failure_mode,
                "evidence": m.evidence,
                "severity": m.severity,
            }
            for m in pred.active_precursors
        ],
        "precursor_warning_level": pred.precursor_warning_level,
        "analog_archetype": pred.analog_archetype,
        "analog_failure_rate": pred.analog_failure_rate,
        "analog_narrative": pred.analog_narrative,
        "top_adversarial_scenarios": pred.top_adversarial_scenarios,
        "mitigation_gaps": pred.mitigation_gaps,
        "ensemble_confidence": pred.ensemble_confidence,
        "robust_nodes": pred.robust_nodes,
        "contested_nodes": pred.contested_nodes,
        "hidden_nodes": pred.hidden_nodes,
        "dominant_failure_mode": pred.dominant_failure_mode,
        "highest_strength_chain": pred.highest_strength_chain,
        "uncertainty": {
            "graph_completeness": pred.uncertainty.graph_completeness,
            "timing_confidence": pred.uncertainty.timing_confidence,
            "mechanism_confidence": pred.uncertainty.mechanism_confidence,
            "novel_situation_risk": pred.uncertainty.novel_situation_risk,
            "irreducible_unknowns": pred.uncertainty.irreducible_unknowns,
        },
    }
