"""
Backtest Scenarios
------------------
Six named scenarios with known ground-truth failure outcomes.

Each scenario provides:
  - graph:            the structural model (Graph)
  - history:          synthetic telemetry trending toward the failure point
  - ground_truth:     what actually happens (node, hours, mechanism)
  - description:      plain-language summary

Scenario types:
  CASCADE_SPOF         — single high-criticality gateway failing under rising load
  VENDOR_COLLAPSE      — vendor reliability declining below threshold
  AUTHORITY_VACUUM     — sole approver overloading, blocks all downstream work
  SILENT_DRIFT         — slow multi-node drift; no single alarm fires early
  COMPOUND_FAILURE     — two independent nodes degrading simultaneously
  FALSE_ALARM          — noisy-but-stable node; oracle should NOT predict failure
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.models.graph import (
    Graph, Node, Edge,
    NodeType, EdgeType,
    NodeAttributes, EdgeAttributes,
)
from app.engines.threshold import NodeStateReading
from app.engines.causal import MechanismType


@dataclass
class GroundTruth:
    failure_node_id: str
    failure_node_label: str
    failure_hours: float            # hours from "now" until actual failure
    mechanism: MechanismType
    secondary_failures: list[str] = field(default_factory=list)  # cascade victims
    is_stable: bool = False         # True → expect NO imminent failure prediction


@dataclass
class BacktestScenario:
    name: str
    description: str
    graph: Graph
    history: dict[str, list[NodeStateReading]]
    ground_truth: GroundTruth
    tags: list[str] = field(default_factory=list)


def _readings(
    n: int,
    load_start: float,
    load_slope: float,
    reliability_start: float = 0.9,
    reliability_slope: float = -0.002,
    stress_start: float = 0.1,
    stress_slope: float = 0.005,
    hours_spacing: float = 1.0,
) -> list[NodeStateReading]:
    """Generate n synthetic readings with a linear trend."""
    now = datetime.now(timezone.utc)
    out = []
    for i in range(n):
        ts = now - timedelta(hours=(n - i) * hours_spacing)
        out.append(NodeStateReading(
            timestamp=ts,
            load=max(0.0, min(1.0, load_start + load_slope * i)),
            reliability=max(0.0, min(1.0, reliability_start + reliability_slope * i)),
            stress=max(0.0, min(1.0, stress_start + stress_slope * i)),
            source="backtest",
        ))
    return out


def _stable_readings(n: int, base_load: float = 0.45) -> list[NodeStateReading]:
    """Generate n stable readings with slight oscillation, no trend."""
    import math
    now = datetime.now(timezone.utc)
    out = []
    for i in range(n):
        ts = now - timedelta(hours=(n - i))
        # sine oscillation — no net drift
        load = base_load + 0.08 * math.sin(i * 0.7)
        reliability = 0.85 + 0.05 * math.cos(i * 0.5)
        out.append(NodeStateReading(
            timestamp=ts,
            load=max(0.0, min(1.0, load)),
            reliability=max(0.0, min(1.0, reliability)),
            stress=0.1,
            source="backtest",
        ))
    return out


# ---------------------------------------------------------------------------
# Scenario 1: CASCADE_SPOF
# A single gateway node under accelerating load feeds four downstream nodes.
# Load trajectory: 0.55 → 0.82 over 18 readings (~18h of history).
# At current rate (+0.015/h) it will cross 0.85 in ~2h.
# Expected: oracle flags gateway as CRITICAL, predicts ~2h to failure.
# ---------------------------------------------------------------------------

def scenario_cascade_spof() -> BacktestScenario:
    nodes = [
        Node(id="gw",  label="Gateway API",    node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.95, replaceability=0.05, load=0.82)),
        Node(id="svc1", label="Auth Service",  node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.8,  replaceability=0.2,  load=0.5)),
        Node(id="svc2", label="Data Service",  node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.75, replaceability=0.25, load=0.45)),
        Node(id="svc3", label="Notify Service",node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.6,  replaceability=0.4,  load=0.3)),
        Node(id="out",  label="Client Output", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(criticality=0.5,  replaceability=0.6,  load=0.2)),
    ]
    edges = [
        Edge(id="e1", source="gw",   target="svc1", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.95)),
        Edge(id="e2", source="gw",   target="svc2", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e3", source="gw",   target="svc3", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.85)),
        Edge(id="e4", source="svc1", target="out",  edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e5", source="svc2", target="out",  edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
    ]
    graph = Graph(id="bt_cascade_spof", name="CASCADE_SPOF", nodes=nodes, edges=edges)

    # Gateway: load 0.55 → 0.82 over 18h (+0.015/h); crosses 0.85 in ~2h
    history = {
        "gw": _readings(18, load_start=0.55, load_slope=0.015,
                        reliability_start=0.92, reliability_slope=-0.003),
        "svc1": _readings(10, load_start=0.40, load_slope=0.005),
        "svc2": _readings(10, load_start=0.35, load_slope=0.004),
    }

    return BacktestScenario(
        name="CASCADE_SPOF",
        description=(
            "Single gateway node under accelerating load (+1.5%/h). "
            "Feeds four downstream services. Load crosses failure threshold in ~2h. "
            "Oracle should flag gateway as CRITICAL and predict ~2h."
        ),
        graph=graph,
        history=history,
        ground_truth=GroundTruth(
            failure_node_id="gw",
            failure_node_label="Gateway API",
            failure_hours=2.0,
            mechanism=MechanismType.RESOURCE_FEEDS,
            secondary_failures=["svc1", "svc2", "svc3"],
        ),
        tags=["spof", "load", "cascade"],
    )


# ---------------------------------------------------------------------------
# Scenario 2: VENDOR_COLLAPSE
# Vendor reliability declining sharply; feeds the core system via FUNDS.
# Reliability: 0.88 → 0.32 over 28 readings (-0.02/h).
# At current rate it will drop below 0.2 in ~6h.
# Expected: oracle detects RELIABILITY_DECAY precursor, ~6h to failure.
# ---------------------------------------------------------------------------

def scenario_vendor_collapse() -> BacktestScenario:
    nodes = [
        Node(id="vendor", label="Cloud Vendor",   node_type=NodeType.VENDOR,
             attributes=NodeAttributes(criticality=0.85, replaceability=0.1, load=0.5)),
        Node(id="core",   label="Core Platform",  node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.9,  replaceability=0.15, load=0.6)),
        Node(id="team",   label="Eng Team",       node_type=NodeType.TEAM,
             attributes=NodeAttributes(criticality=0.7,  replaceability=0.3,  load=0.55)),
        Node(id="output", label="Product",        node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(criticality=0.8,  replaceability=0.2,  load=0.4)),
    ]
    edges = [
        Edge(id="e1", source="vendor", target="core",   edge_type=EdgeType.FUNDS,
             attributes=EdgeAttributes(reliability=0.32)),
        Edge(id="e2", source="core",   target="output", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e3", source="team",   target="core",   edge_type=EdgeType.APPROVES,
             attributes=EdgeAttributes(reliability=0.95)),
    ]
    graph = Graph(id="bt_vendor_collapse", name="VENDOR_COLLAPSE", nodes=nodes, edges=edges)

    history = {
        "vendor": _readings(28, load_start=0.5, load_slope=0.002,
                            reliability_start=0.88, reliability_slope=-0.020),
        "core":   _readings(15, load_start=0.55, load_slope=0.003,
                            reliability_start=0.85, reliability_slope=-0.005),
    }

    return BacktestScenario(
        name="VENDOR_COLLAPSE",
        description=(
            "Vendor reliability declining at -2%/h (SLA degradation). "
            "Core platform funded by vendor. Reliability drops below 0.20 in ~6h. "
            "Oracle should detect reliability decay precursor and FINANCIAL_FUNDS mechanism."
        ),
        graph=graph,
        history=history,
        ground_truth=GroundTruth(
            failure_node_id="vendor",
            failure_node_label="Cloud Vendor",
            failure_hours=6.0,
            mechanism=MechanismType.FINANCIAL_FUNDS,
            secondary_failures=["core", "output"],
        ),
        tags=["vendor", "reliability", "financial"],
    )


# ---------------------------------------------------------------------------
# Scenario 3: AUTHORITY_VACUUM
# Sole approver overloaded; all downstream processes need their approval.
# Approver load: 0.60 → 0.87 over 18h (+0.015/h); crosses threshold in ~2h.
# Expected: oracle detects APPROVAL_GATES chain, ~2h, CRITICAL status.
# ---------------------------------------------------------------------------

def scenario_authority_vacuum() -> BacktestScenario:
    nodes = [
        Node(id="cto",   label="CTO",          node_type=NodeType.PERSON,
             attributes=NodeAttributes(criticality=0.95, replaceability=0.05, load=0.87,
                                       visibility=0.5)),
        Node(id="proc1", label="Budget Approval",  node_type=NodeType.PROCESS_STEP,
             attributes=NodeAttributes(criticality=0.8, replaceability=0.2, load=0.7)),
        Node(id="proc2", label="Hire Approval",    node_type=NodeType.PROCESS_STEP,
             attributes=NodeAttributes(criticality=0.75, replaceability=0.3, load=0.65)),
        Node(id="proc3", label="Vendor Contracts", node_type=NodeType.PROCESS_STEP,
             attributes=NodeAttributes(criticality=0.8, replaceability=0.15, load=0.6)),
        Node(id="board", label="Board",        node_type=NodeType.TEAM,
             attributes=NodeAttributes(criticality=0.6, replaceability=0.5, load=0.3)),
    ]
    edges = [
        Edge(id="e1", source="cto",   target="proc1", edge_type=EdgeType.APPROVES,
             attributes=EdgeAttributes(reliability=0.95)),
        Edge(id="e2", source="cto",   target="proc2", edge_type=EdgeType.APPROVES,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e3", source="cto",   target="proc3", edge_type=EdgeType.APPROVES,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e4", source="board", target="cto",   edge_type=EdgeType.GOVERNED_BY,
             attributes=EdgeAttributes(reliability=0.8)),
    ]
    graph = Graph(id="bt_authority_vacuum", name="AUTHORITY_VACUUM", nodes=nodes, edges=edges)

    history = {
        "cto": _readings(18, load_start=0.60, load_slope=0.015,
                         reliability_start=0.88, reliability_slope=-0.005),
        "proc1": _readings(10, load_start=0.65, load_slope=0.003),
        "proc2": _readings(10, load_start=0.60, load_slope=0.002),
    }

    return BacktestScenario(
        name="AUTHORITY_VACUUM",
        description=(
            "Single approver (CTO) required for 3 critical processes. "
            "Load rising at +1.5%/h; crosses failure threshold in ~2h. "
            "Oracle should detect APPROVAL_GATES mechanism and authority vacuum precursor."
        ),
        graph=graph,
        history=history,
        ground_truth=GroundTruth(
            failure_node_id="cto",
            failure_node_label="CTO",
            failure_hours=2.0,
            mechanism=MechanismType.APPROVAL_GATES,
            secondary_failures=["proc1", "proc2", "proc3"],
        ),
        tags=["authority", "approval", "spof"],
    )


# ---------------------------------------------------------------------------
# Scenario 4: SILENT_DRIFT
# Six nodes all drifting slowly upward (+0.003/h). No single alarm fires.
# Individually they look fine; collectively 3 converge on failure in ~40h.
# Expected: oracle detects DRIFTING status across multiple nodes, warns of
# compound risk within 48h. Tests multi-node temporal reasoning.
# ---------------------------------------------------------------------------

def scenario_silent_drift() -> BacktestScenario:
    nodes = [
        Node(id="n1", label="Data Pipeline",   node_type=NodeType.PROCESS_STEP,
             attributes=NodeAttributes(criticality=0.8, replaceability=0.2, load=0.67)),
        Node(id="n2", label="ML Model",        node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.75, replaceability=0.25, load=0.65)),
        Node(id="n3", label="Feature Store",   node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.7, replaceability=0.3, load=0.63)),
        Node(id="n4", label="Inference API",   node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.85, replaceability=0.1, load=0.60)),
        Node(id="n5", label="Monitoring",      node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.5, replaceability=0.6, load=0.40)),
        Node(id="n6", label="Report Output",   node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(criticality=0.6, replaceability=0.4, load=0.35)),
    ]
    edges = [
        Edge(id="e1", source="n3",  target="n1",  edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e2", source="n1",  target="n2",  edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.85)),
        Edge(id="e3", source="n2",  target="n4",  edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e4", source="n4",  target="n6",  edge_type=EdgeType.INFORMS,
             attributes=EdgeAttributes(reliability=0.95)),
        Edge(id="e5", source="n5",  target="n4",  edge_type=EdgeType.INFORMS,
             attributes=EdgeAttributes(reliability=0.8)),
    ]
    graph = Graph(id="bt_silent_drift", name="SILENT_DRIFT", nodes=nodes, edges=edges)

    # All nodes drifting at +0.4%/h — slow but consistent.
    # With these starting loads, n1 and n4 will be in DRIFTING range (24-72h).
    history = {
        "n1": _readings(24, load_start=0.65, load_slope=0.004,
                        reliability_start=0.88, reliability_slope=-0.003),
        "n2": _readings(24, load_start=0.63, load_slope=0.004),
        "n3": _readings(24, load_start=0.61, load_slope=0.004),
        "n4": _readings(24, load_start=0.59, load_slope=0.004,
                        reliability_start=0.85, reliability_slope=-0.004),
        "n5": _readings(20, load_start=0.38, load_slope=0.002),
    }

    return BacktestScenario(
        name="SILENT_DRIFT",
        description=(
            "Six-node ML pipeline, all nodes drifting at +0.3%/h. "
            "No single node near threshold today; n1 and n4 converge on failure in ~40h. "
            "Tests oracle's ability to detect slow compound drift before any alarm fires."
        ),
        graph=graph,
        history=history,
        ground_truth=GroundTruth(
            failure_node_id="n1",
            failure_node_label="Data Pipeline",
            failure_hours=40.0,
            mechanism=MechanismType.RESOURCE_FEEDS,
            secondary_failures=["n2", "n4"],
        ),
        tags=["drift", "slow", "compound", "ml"],
    )


# ---------------------------------------------------------------------------
# Scenario 5: COMPOUND_FAILURE
# Two independent critical nodes degrading on different timescales.
# Node A (compute): load rising fast → fails in ~6h
# Node B (database): reliability declining → fails in ~14h
# Expected: oracle detects compound risk; A is primary, B is secondary.
# Adversarial engine should surface the A+B combination.
# ---------------------------------------------------------------------------

def scenario_compound_failure() -> BacktestScenario:
    nodes = [
        Node(id="compute", label="Compute Cluster", node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.9, replaceability=0.1, load=0.80)),
        Node(id="db",      label="Primary DB",      node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.9, replaceability=0.1, load=0.55)),
        Node(id="cache",   label="Cache Layer",     node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.6, replaceability=0.4, load=0.4)),
        Node(id="app",     label="App Server",      node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.85, replaceability=0.2, load=0.6)),
        Node(id="lb",      label="Load Balancer",   node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.8, replaceability=0.15, load=0.5)),
    ]
    edges = [
        Edge(id="e1", source="lb",      target="app",     edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.95)),
        Edge(id="e2", source="app",     target="compute", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e3", source="app",     target="db",      edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e4", source="cache",   target="db",      edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.85)),
        Edge(id="e5", source="compute", target="db",      edge_type=EdgeType.INFORMS,
             attributes=EdgeAttributes(reliability=0.8)),
    ]
    graph = Graph(id="bt_compound", name="COMPOUND_FAILURE", nodes=nodes, edges=edges)

    history = {
        # Compute: fast rising load, ~6h to threshold
        "compute": _readings(16, load_start=0.62, load_slope=0.012,
                             reliability_start=0.9, reliability_slope=-0.002),
        # DB: reliability degrading, ~14h to failure
        "db":      _readings(20, load_start=0.50, load_slope=0.002,
                             reliability_start=0.80, reliability_slope=-0.043),
        "app":     _readings(12, load_start=0.55, load_slope=0.003),
        "cache":   _readings(10, load_start=0.38, load_slope=0.001),
    }

    return BacktestScenario(
        name="COMPOUND_FAILURE",
        description=(
            "Compute cluster load rising (+1.2%/h, fails ~6h) and "
            "primary DB reliability declining (-4.3%/h, fails ~14h) — independently. "
            "Oracle should detect the compound risk; adversarial engine should surface "
            "the (compute, db) combination as highest-damage scenario."
        ),
        graph=graph,
        history=history,
        ground_truth=GroundTruth(
            failure_node_id="compute",
            failure_node_label="Compute Cluster",
            failure_hours=6.0,
            mechanism=MechanismType.RESOURCE_FEEDS,
            secondary_failures=["db", "app"],
        ),
        tags=["compound", "multi-node", "adversarial"],
    )


# ---------------------------------------------------------------------------
# Scenario 6: FALSE_ALARM
# Noisy but stable node — oscillating load, no net drift.
# Oracle should NOT classify this as APPROACHING/CRITICAL.
# Specificity test: correct answer is "no imminent failure".
# ---------------------------------------------------------------------------

def scenario_false_alarm() -> BacktestScenario:
    nodes = [
        Node(id="svc",  label="Batch Service",  node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.6, replaceability=0.5, load=0.45)),
        Node(id="db",   label="Archive DB",     node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.5, replaceability=0.6, load=0.40)),
        Node(id="cron", label="Cron Scheduler", node_type=NodeType.PROCESS_STEP,
             attributes=NodeAttributes(criticality=0.4, replaceability=0.7, load=0.35)),
    ]
    edges = [
        Edge(id="e1", source="cron", target="svc", edge_type=EdgeType.TIMED_BEFORE,
             attributes=EdgeAttributes(reliability=0.95)),
        Edge(id="e2", source="svc",  target="db",  edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.9)),
    ]
    graph = Graph(id="bt_false_alarm", name="FALSE_ALARM", nodes=nodes, edges=edges)

    history = {
        "svc":  _stable_readings(24, base_load=0.45),
        "db":   _stable_readings(24, base_load=0.40),
        "cron": _stable_readings(20, base_load=0.35),
    }

    return BacktestScenario(
        name="FALSE_ALARM",
        description=(
            "Noisy but fundamentally stable service — oscillating load with no trend. "
            "Oracle should NOT flag any node as APPROACHING or CRITICAL. "
            "Tests specificity: false positives reduce oracle credibility."
        ),
        graph=graph,
        history=history,
        ground_truth=GroundTruth(
            failure_node_id="svc",
            failure_node_label="Batch Service",
            failure_hours=999.0,   # effectively never
            mechanism=MechanismType.UNKNOWN,
            is_stable=True,
        ),
        tags=["stable", "specificity", "false-alarm"],
    )


def all_scenarios() -> list[BacktestScenario]:
    return [
        scenario_cascade_spof(),
        scenario_vendor_collapse(),
        scenario_authority_vacuum(),
        scenario_silent_drift(),
        scenario_compound_failure(),
        scenario_false_alarm(),
    ]
