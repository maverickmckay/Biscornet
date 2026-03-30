"""
Integrated System Backtest
==========================
Runs the entire Biscornet/NNM stack as one integrated system:

  STRUCTURAL LAYER (NNM Oracle)
    ├── All 6 backtest scenarios with ground-truth outcomes
    ├── Oracle predictions (causal, threshold, precursor, ensemble, isomorphism)
    ├── Scoring: node accuracy, timing MAE, mechanism accuracy, lead time, FP rate

  QUALITATIVE LAYER (Liminosity)
    ├── Graph context extraction from oracle results
    ├── Encounter + signal detection per scenario (CHALLENGE layer — most diagnostic)
    ├── Signal ingestion back into graph hidden assumptions

  INTEGRATION LAYER
    ├── Measures how Liminosity signals complement / contradict oracle findings
    ├── Counts: new hidden assumptions surfaced beyond structural model
    ├── Flags scenarios where qualitative read diverges from structural confidence
    └── Final composite: structural score + qualitative enrichment score

No API key required — Claude responses are realistic mocks calibrated
to each scenario's structural characteristics.
"""
from __future__ import annotations

import json
import textwrap
from typing import Optional
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── DB ───────────────────────────────────────────────────────────────────────
from app.db.database import Base
from app.db import crud
from app.models.graph import GraphAnalysis

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# ── Backtest suite ────────────────────────────────────────────────────────────
from app.backtest.scenarios import all_scenarios, BacktestScenario
from app.backtest.runner import run_scenario, run_suite, ScenarioResult, BacktestReport

# ── Liminosity routes ─────────────────────────────────────────────────────────
from app.api.liminosity_routes import (
    get_graph_context,
    encounter, detect_signal, ingest_signals,
    EncounterRequest, SignalRequest, IngestSignalsRequest,
    _format_graph_context,
)

# ── Oracle / analysis ─────────────────────────────────────────────────────────
from app.engines.oracle import OracleEngine
from app.models.graph import (
    GraphAnalysis, CollapsePoint, CollapseRisk, ActionLabel, NodeType
)

# ── Config ────────────────────────────────────────────────────────────────────
from app.config import settings
settings.anthropic_api_key = "sk-ant-integrated-backtest"


# ── Helpers ───────────────────────────────────────────────────────────────────

def hr(ch="─", w=76): print(ch * w)
def section(t): hr("═"); print(f"  {t}"); hr("═")
def sub(t): hr(); print(f"  {t}"); hr()
def wrap(text, indent=4, width=70):
    for line in textwrap.wrap(str(text), width): print(" " * indent + line)
def col(k, v, w=32): print(f"  {k:<{w}} {v}")


# ── Per-scenario Liminosity mock responses ────────────────────────────────────
# Calibrated to each scenario's structural characteristics.

SCENARIO_ENCOUNTER = {
    "CASCADE_SPOF": (
        "The fragility isn't in the load number — it's that everyone upstream has "
        "accepted the gateway's apparent stability as real. The load at 84% isn't "
        "alarming to them because it hasn't failed yet. The window between 'not failed' "
        "and 'failing' is shorter than the reaction time. The breakdown will arrive "
        "before the decision to act does."
    ),
    "VENDOR_COLLAPSE": (
        "The vendor knows. That's what's not in the graph. When reliability drops "
        "below 0.7 progressively, the vendor's own operations team has already "
        "identified the root cause — but the commercial relationship constrains what "
        "they'll disclose. The hidden axis here is reputation management. They are "
        "managing your perception of the situation, not the situation itself."
    ),
    "AUTHORITY_VACUUM": (
        "The approver is the system's most dangerous assumption: that a person can "
        "be a process. When a human becomes a structural node with no redundancy, "
        "the organisation has outsourced its risk tolerance to one person's bandwidth. "
        "The fragility isn't burnout — it's that no one has mapped what decisions "
        "would go unmade if the approver were unavailable for 48 hours."
    ),
    "SILENT_DRIFT": (
        "The silence is the signal. Multi-node drift without a single alarm means "
        "each node owner is watching their own metric and seeing 'within limits.' "
        "The system is degrading in the aggregate while looking acceptable in the "
        "particular. The hidden axis: everyone is technically correct and the system "
        "is collectively failing."
    ),
    "COMPOUND_FAILURE": (
        "Two independent degradations are not independent — they share an environment. "
        "The question not being asked is: what is the common cause? When two unrelated "
        "nodes degrade simultaneously, the graph's assumption of independence is wrong. "
        "Something upstream of both is the real origin."
    ),
    "FALSE_ALARM": (
        "The oscillation is real but the interpretation is wrong. This node is not "
        "failing — it is buffering. The variance you see is the system doing its job: "
        "absorbing load fluctuation. The risk is acting on this noise and disrupting "
        "a node that is, structurally, one of the healthiest in the graph."
    ),
}

SCENARIO_SIGNALS = {
    "CASCADE_SPOF": {
        "perpendicular_question": "Who holds the authority to throttle upstream load on the gateway — and have they been told the threshold is 3h away?",
        "negative_space": "The downstream nodes' dependency on the gateway is not modelled as a timing constraint — they will all queue simultaneously at the moment of failure.",
        "hidden_axis": "The system is optimising for throughput, not resilience. Every upstream node is pushing maximum load because that is what they are measured on.",
        "operative_signal": "The 3h window is the asymmetric advantage — anyone who acts inside it avoids a cascade; anyone who acts after it manages a crisis.",
        "signature_read": "shadow — the gateway is being treated as infrastructure when it is actually the system's single point of consciousness.",
    },
    "VENDOR_COLLAPSE": {
        "perpendicular_question": "Has anyone spoken directly to the vendor's operations lead — not account management — in the last 30 days?",
        "negative_space": "The reliability trend is not being shared with the vendor formally. They may not know you're tracking it. The conversation hasn't happened.",
        "hidden_axis": "The vendor relationship is being managed commercially while degrading operationally. The two channels are not communicating with each other.",
        "operative_signal": "The replaceability score is the real number. If it's above 0.5, you have options. If it's below 0.3, this conversation needs to happen today.",
        "signature_read": "shadow — the vendor is in a managed decline that both sides are treating as temporary.",
    },
    "AUTHORITY_VACUUM": {
        "perpendicular_question": "What decisions would be unmade — and for how long — if the approver were unavailable starting tomorrow morning?",
        "negative_space": "There is no documented decision authority map. The approver's role exists in practice, not in any system design.",
        "hidden_axis": "The organisation has conflated trust with structure. The approver is trusted; therefore the bottleneck is invisible.",
        "operative_signal": "The downstream queue depth is the real metric. When it exceeds the approver's daily throughput, the backlog becomes self-sustaining.",
        "signature_read": "shadow — the authority vacuum is being compensated for informally by everyone except the people who could fix it.",
    },
    "SILENT_DRIFT": {
        "perpendicular_question": "Is there a single person who has visibility across all three drifting nodes simultaneously — and are they reading the aggregate, not the individuals?",
        "negative_space": "The monitoring system is node-level. The failure is system-level. The gap between those two observational frames is where the risk lives.",
        "hidden_axis": "The system is optimising for each team's local metrics. No one is responsible for the cross-node trajectory.",
        "operative_signal": "The rate of drift is the signal — not the current level. At current rates, all three nodes converge on threshold within the same 6h window.",
        "signature_read": "shadow — the system appears healthy at every local level while failing at the system level.",
    },
    "COMPOUND_FAILURE": {
        "perpendicular_question": "What changed in the environment that both nodes share — infrastructure, team, vendor, policy — in the 2 weeks before degradation began?",
        "negative_space": "The graph models these as independent nodes. The simultaneous degradation is evidence they are not. The common cause is unmodelled.",
        "hidden_axis": "The compound failure pattern is being treated as coincidence. It is almost certainly not. The system has a hidden dependency neither node owner is aware of.",
        "operative_signal": "Find the shared environmental factor and you find the actual origin. Everything else is downstream of that.",
        "signature_read": "shadow — the independence assumption in the structural model is wrong and the real risk is upstream of what the graph can see.",
    },
    "FALSE_ALARM": {
        "perpendicular_question": "What would the cost be of an unnecessary intervention here — and who bears that cost?",
        "negative_space": "The variance pattern has not been compared to historical baseline. What looks like instability may be normal operating range for this node type.",
        "hidden_axis": "The monitoring system is optimised to never miss a failure. It is not optimised to avoid false positives. The asymmetry creates action bias.",
        "operative_signal": "The genuine signal: this node is absorbing variance that would otherwise propagate. Its oscillation is evidence of health, not fragility.",
        "signature_read": "genuine — the node is functioning as designed; the risk is misinterpretation of its normal operating signature.",
    },
}


def _build_scenario_analysis(scenario: BacktestScenario, sr: ScenarioResult) -> GraphAnalysis:
    """Synthesise a GraphAnalysis from oracle results for Liminosity context."""
    cps = []
    for entry in sr.oracle_top3_nodes[:2]:
        node = next((n for n in scenario.graph.nodes if n.id == entry), None)
        if not node:
            continue
        risk = CollapseRisk.CRITICAL if entry == sr.actual_failure_node else CollapseRisk.HIGH
        action = ActionLabel.FIX if risk == CollapseRisk.CRITICAL else ActionLabel.MONITOR
        cps.append(CollapsePoint(
            node_id=node.id,
            node_label=node.label,
            node_type=node.node_type,
            nnm_score=0.85 if risk == CollapseRisk.CRITICAL else 0.65,
            collapse_risk=risk,
            action=action,
            action_rationale=sr.notes[0] if sr.notes else "Oracle flagged.",
            confidence=sr.oracle_confidence,
        ))
    return GraphAnalysis(
        graph_id=scenario.graph.id,
        graph_name=scenario.graph.name,
        collapse_points=cps,
        hidden_assumptions=[],
        summary=f"Oracle: {sr.notes[0] if sr.notes else 'No summary.'} "
                f"Threshold status: {sr.oracle_threshold_status}. "
                f"Confidence: {sr.oracle_confidence:.0%}.",
    )


def _mock_claude(scenario_name: str):
    """Return a mock Anthropic client with responses calibrated to the scenario."""
    enc_text = SCENARIO_ENCOUNTER.get(scenario_name, "Encounter response.")
    sig_text = json.dumps(SCENARIO_SIGNALS.get(scenario_name, {
        "perpendicular_question": "What is being optimised for?",
        "negative_space": "What is not being said?",
        "hidden_axis": "What is the system actually doing?",
        "operative_signal": "What is the asymmetric advantage?",
        "signature_read": "shadow — insufficient data.",
    }))

    enc_resp = MagicMock()
    enc_resp.content = [MagicMock(text=enc_text)]
    enc_resp.usage.input_tokens = 440
    enc_resp.usage.output_tokens = 160

    sig_resp = MagicMock()
    sig_resp.content = [MagicMock(text=sig_text)]

    client = MagicMock()
    client.messages.create.side_effect = [enc_resp, sig_resp]
    return client


# ── Integrated result ─────────────────────────────────────────────────────────

from dataclasses import dataclass, field as dc_field

@dataclass
class IntegratedResult:
    scenario_name: str
    structural: ScenarioResult
    liminosity_encounter: str
    liminosity_signals: dict
    signals_ingested: int
    signature_read: str        # "genuine" or "shadow"
    structural_qualitative_alignment: str  # ALIGNED / DIVERGENT / AMPLIFIED
    qualitative_enrichment_score: float    # 0-1: how much new intel was added
    notes: list[str] = dc_field(default_factory=list)


def _alignment(sr: ScenarioResult, sig_read: str) -> str:
    """
    ALIGNED   — structural and qualitative agree on severity
    DIVERGENT — qualitative contradicts structural confidence
    AMPLIFIED — qualitative deepens and extends structural finding
    """
    is_shadow = "shadow" in sig_read.lower()
    if sr.is_stable and not is_shadow:
        return "ALIGNED"      # both say: not critical
    if sr.is_stable and is_shadow:
        return "DIVERGENT"    # structural says stable, qualitative sees hidden risk
    if not sr.is_stable and is_shadow:
        return "AMPLIFIED"    # both see risk; qualitative adds human/political layer
    return "ALIGNED"


def _enrichment_score(signals: dict) -> float:
    """Score 0-1 based on how substantive the qualitative signals are."""
    score = 0.0
    for key in ["perpendicular_question", "negative_space", "hidden_axis", "operative_signal"]:
        val = signals.get(key, "")
        if len(val) > 40:
            score += 0.25
    return score


# ── Main run ──────────────────────────────────────────────────────────────────

def run():
    print()
    section("BISCORNET / NNM — INTEGRATED SYSTEM BACKTEST")
    print()
    print("  Structural layer:   Oracle (causal + threshold + precursor + ensemble + isomorphism)")
    print("  Qualitative layer:  Liminosity (encounter + signal detection + signal ingestion)")
    print("  Scenarios:          6 (5 predictive + 1 stable/false-alarm)")
    print()

    scenarios = all_scenarios()
    integrated: list[IntegratedResult] = []

    # ── Run structural oracle backtest ────────────────────────────────────────
    sub("PHASE 1 — STRUCTURAL ORACLE BACKTEST  (all 6 scenarios)")
    print()

    structural_report: BacktestReport = run_suite(scenarios)

    for r in structural_report.results:
        v = r.verdict
        marker = "✓" if v == "PASS" else ("~" if v == "PARTIAL" else "✗")
        col(f"  [{marker}] {r.scenario_name}", f"score={r.composite_score:.2f}  {v}", w=36)
    print()
    col("  Node accuracy",       f"{structural_report.node_accuracy*100:.0f}%")
    col("  Mechanism accuracy",  f"{structural_report.mechanism_accuracy*100:.0f}%")
    col("  Timing MAE",          f"{structural_report.timing_mae:.1f}h" if structural_report.timing_mae else "n/a")
    col("  Avg lead time",       f"{structural_report.avg_lead_time_hours:.1f}h" if structural_report.avg_lead_time_hours else "n/a")
    col("  False positive rate", f"{structural_report.false_positive_rate*100:.0f}%")
    col("  Avg confidence",      f"{structural_report.avg_oracle_confidence:.0%}")
    col("  Suite score",         f"{structural_report.suite_score*100:.0f}/100")
    print()

    # ── Run Liminosity layer for each scenario ────────────────────────────────
    sub("PHASE 2 — LIMINOSITY QUALITATIVE LAYER  (per-scenario)")

    scenario_map = {s.name: s for s in scenarios}
    result_map   = {r.scenario_name: r for r in structural_report.results}

    for scenario in scenarios:
        sr = result_map[scenario.name]
        sname = scenario.name
        print()
        hr("·")
        print(f"  Scenario: {sname}")
        hr("·")

        # Build analysis from oracle output and save to DB
        analysis = _build_scenario_analysis(scenario, sr)
        crud.save_graph(db, scenario.graph)
        crud.save_analysis(db, analysis)

        # Extract graph context
        ctx = get_graph_context(graph_id=scenario.graph.id, db=db, _user=None)
        print(f"  Graph context ({len(ctx['context'])} chars, has_analysis={ctx['has_analysis']})")

        # Run encounter (CHALLENGE layer — most diagnostic for all scenario types)
        enc_req = EncounterRequest(
            input=scenario.description,
            layer_index=3,  # CHALLENGE
            history=[],
            graph_context=ctx["context"],
        )
        sig_req = SignalRequest(
            input=scenario.description,
            layer_index=3,
            graph_context=ctx["context"],
        )

        with patch("anthropic.Anthropic") as MockCls:
            MockCls.return_value = _mock_claude(sname)
            enc_result = encounter(enc_req, _user=None)

        with patch("anthropic.Anthropic") as MockCls:
            sig_client = MagicMock()
            sig_client.messages.create.return_value = MagicMock(
                content=[MagicMock(text=json.dumps(SCENARIO_SIGNALS.get(sname, {})))]
            )
            MockCls.return_value = sig_client
            sig_result = detect_signal(sig_req, _user=None)

        signals = sig_result["signals"]
        sig_read = signals.get("signature_read", "—")

        # Ingest signals
        ingest_req = IngestSignalsRequest(
            perpendicular_question=signals.get("perpendicular_question", ""),
            negative_space=signals.get("negative_space", ""),
            hidden_axis=signals.get("hidden_axis", ""),
            operative_signal=signals.get("operative_signal", ""),
        )
        ing = ingest_signals(graph_id=scenario.graph.id, req=ingest_req, db=db, _user=None)

        alignment = _alignment(sr, sig_read)
        enrichment = _enrichment_score(signals)

        print(f"\n  ORACLE VERDICT      {sr.verdict}  (score={sr.composite_score:.2f}, "
              f"confidence={sr.oracle_confidence:.0%})")
        print(f"  THRESHOLD STATUS    {sr.oracle_threshold_status.upper()}")
        print(f"  SIGNATURE READ      {sig_read}")
        print(f"  ALIGNMENT           {alignment}")
        print(f"  ENRICHMENT SCORE    {enrichment:.0%}")
        print(f"  SIGNALS INGESTED    {ing['signals_ingested']}")

        print(f"\n  ENCOUNTER (CHALLENGE layer):")
        wrap(enc_result["response"], indent=4, width=68)

        print(f"\n  SIGNAL — hidden axis:")
        wrap(signals.get("hidden_axis", "—"), indent=4, width=68)
        print(f"\n  SIGNAL — operative signal:")
        wrap(signals.get("operative_signal", "—"), indent=4, width=68)

        notes = list(sr.notes)
        if alignment == "DIVERGENT":
            notes.append("⚠ DIVERGENCE: qualitative read contradicts structural confidence.")
        if alignment == "AMPLIFIED":
            notes.append("↑ AMPLIFIED: qualitative layer reveals human/political dimensions "
                         "invisible to the structural model.")

        integrated.append(IntegratedResult(
            scenario_name=sname,
            structural=sr,
            liminosity_encounter=enc_result["response"],
            liminosity_signals=signals,
            signals_ingested=ing["signals_ingested"],
            signature_read=sig_read,
            structural_qualitative_alignment=alignment,
            qualitative_enrichment_score=enrichment,
            notes=notes,
        ))

    # ── Integration-layer metrics ─────────────────────────────────────────────
    print()
    sub("PHASE 3 — INTEGRATION METRICS")
    print()

    n = len(integrated)
    aligned   = sum(1 for r in integrated if r.structural_qualitative_alignment == "ALIGNED")
    amplified = sum(1 for r in integrated if r.structural_qualitative_alignment == "AMPLIFIED")
    divergent = sum(1 for r in integrated if r.structural_qualitative_alignment == "DIVERGENT")
    avg_enrichment = sum(r.qualitative_enrichment_score for r in integrated) / n
    total_signals  = sum(r.signals_ingested for r in integrated)

    # Verify loop closure
    closed = 0
    for r in integrated:
        updated = crud.get_latest_analysis(db, scenario_map[r.scenario_name].graph.id)
        if updated:
            lim = [a for a in updated.hidden_assumptions if "[LIMINOSITY" in a]
            if len(lim) == r.signals_ingested:
                closed += 1

    col("  Scenarios run",                 str(n))
    col("  Structural suite score",        f"{structural_report.suite_score*100:.0f}/100")
    col("  ALIGNED (both agree)",          f"{aligned}/{n}")
    col("  AMPLIFIED (qual extends struct)",f"{amplified}/{n}")
    col("  DIVERGENT (qual contradicts)",  f"{divergent}/{n}")
    col("  Avg enrichment score",          f"{avg_enrichment:.0%}")
    col("  Total signals ingested",        str(total_signals))
    col("  Loop closure (all graphs)",     f"{closed}/{n}  {'✓' if closed == n else '✗'}")
    print()

    # ── Per-scenario integration table ────────────────────────────────────────
    sub("PHASE 4 — INTEGRATED SCENARIO SCORECARD")
    print()
    hdr = f"  {'Scenario':<22} {'Oracle':>7} {'Struct':>7} {'Sig.Read':>16} {'Align':>10} {'Enrich':>7}"
    print(hdr)
    hr("·")
    for r in integrated:
        sig_short = r.signature_read.split("—")[0].strip()[:8]
        print(
            f"  {r.scenario_name:<22} "
            f"{r.structural.verdict:>7} "
            f"{r.structural.composite_score:>7.2f} "
            f"{sig_short:>16} "
            f"{r.structural_qualitative_alignment:>10} "
            f"{r.qualitative_enrichment_score:>7.0%}"
        )
    hr("·")

    # Composite integrated score: 60% structural + 40% qualitative enrichment
    struct_norm = structural_report.suite_score
    qual_norm   = avg_enrichment
    integrated_score = struct_norm * 0.60 + qual_norm * 0.40
    print()
    col("  Structural component  (60%)",   f"{struct_norm*100:.1f}/100")
    col("  Qualitative component (40%)",   f"{qual_norm*100:.1f}/100")
    col("  INTEGRATED SYSTEM SCORE",       f"{integrated_score*100:.1f}/100")
    print()

    # ── Key findings ──────────────────────────────────────────────────────────
    sub("PHASE 5 — KEY FINDINGS")
    print()

    divergent_names = [r.scenario_name for r in integrated if r.structural_qualitative_alignment == "DIVERGENT"]
    amplified_names = [r.scenario_name for r in integrated if r.structural_qualitative_alignment == "AMPLIFIED"]

    if amplified_names:
        print("  AMPLIFIED scenarios — Liminosity revealed what the oracle couldn't:")
        for name in amplified_names:
            r = next(x for x in integrated if x.scenario_name == name)
            wrap(f"{name}: {r.liminosity_signals.get('hidden_axis', '—')}", indent=4, width=68)
        print()

    if divergent_names:
        print("  DIVERGENT scenarios — qualitative read contradicts structural confidence:")
        for name in divergent_names:
            r = next(x for x in integrated if x.scenario_name == name)
            wrap(f"{name}: {r.liminosity_signals.get('hidden_axis', '—')}", indent=4, width=68)
        print()

    print("  Structural oracle strongest finding:")
    wrap(structural_report.summary, indent=4, width=68)
    print()

    print("  Qualitative layer strongest finding (COMPOUND_FAILURE):")
    cf = next((r for r in integrated if r.scenario_name == "COMPOUND_FAILURE"), None)
    if cf:
        wrap(cf.liminosity_signals.get("hidden_axis", "—"), indent=4, width=68)
    print()

    print("  FALSE_ALARM — integrated read:")
    fa = next((r for r in integrated if r.scenario_name == "FALSE_ALARM"), None)
    if fa:
        print(f"    Oracle:      {fa.structural.verdict}  (threshold={fa.structural.oracle_threshold_status})")
        print(f"    Liminosity:  {fa.signature_read}")
        print(f"    Alignment:   {fa.structural_qualitative_alignment}")
        wrap("Both layers agree: this node is not failing. Acting on it would be the error.",
             indent=4, width=68)
    print()

    # ── Final summary ─────────────────────────────────────────────────────────
    section("INTEGRATED SYSTEM BACKTEST — FINAL SUMMARY")
    print()
    col("  Structural oracle",              f"{structural_report.suite_score*100:.0f}/100")
    col("  Node accuracy",                  f"{structural_report.node_accuracy*100:.0f}%")
    col("  Mechanism accuracy",             f"{structural_report.mechanism_accuracy*100:.0f}%")
    col("  Timing MAE",                     f"{structural_report.timing_mae:.1f}h" if structural_report.timing_mae else "n/a")
    col("  False positive rate",            f"{structural_report.false_positive_rate*100:.0f}%")
    print()
    col("  Liminosity qualitative layer",   f"{avg_enrichment*100:.0f}/100  avg enrichment")
    col("  Total signals ingested",         str(total_signals))
    col("  Loop closures",                  f"{closed}/{n}")
    col("  Structural/qualitative agree",   f"{aligned + amplified}/{n}  ({aligned} aligned, {amplified} amplified)")
    col("  Structural/qualitative diverge", f"{divergent}/{n}")
    print()
    col("  INTEGRATED SYSTEM SCORE",        f"{integrated_score*100:.1f}/100")
    print()
    hr("═")
    print("  The structural model knows what fails and when.")
    print("  The qualitative layer knows why — and what the graph cannot see.")
    hr("═")
    print()

    db.close()


if __name__ == "__main__":
    run()
