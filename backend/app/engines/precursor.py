"""
Precursor Signature Library
----------------------------
Complex systems rarely fail instantaneously. They emit precursor signatures —
specific patterns of small anomalies that reliably precede failure by hours,
days, or weeks.

Individually, each signal looks like noise.
Together, against the right template, they identify the approach of failure
before it becomes visible to observers focused on single metrics.

Built-in signatures (12):
  VELOCITY_SPIKE          — rapid acceleration in load rate
  RELIABILITY_DECAY       — steady monotonic reliability decline
  ISOLATION_PATTERN       — increasing centrality + decreasing connectivity
  CASCADE_PRIMER          — cluster of medium-stress connected nodes
  DARK_PATH_ACTIVATION    — low-visibility paths showing unexpected load
  FALSE_REDUNDANCY_STRESS — redundant paths with correlated load spikes
  FEEDBACK_LOOP           — circular dependency showing oscillating values
  CHOKEPOINT_SATURATION   — high-betweenness node approaching load capacity
  TEMPORAL_TRAP           — time-sensitive path showing latency growth
  ASSUMPTION_EROSION      — assumption/confidence nodes showing decay
  AUTHORITY_VACUUM        — person nodes with spiking load, no escalation
  VENDOR_FRAGILITY        — external nodes showing reliability degradation

Each signature has:
  - A detection function operating on time-series data
  - An estimated historical lead time before failure
  - A failure mode it predicts
  - A description of what to watch for
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from app.models.graph import Graph, NodeType
from app.engines.threshold import NodeStateReading, ProximityScore, ThresholdStatus


class SignatureType(str, Enum):
    VELOCITY_SPIKE         = "velocity_spike"
    RELIABILITY_DECAY      = "reliability_decay"
    ISOLATION_PATTERN      = "isolation_pattern"
    CASCADE_PRIMER         = "cascade_primer"
    DARK_PATH_ACTIVATION   = "dark_path_activation"
    FALSE_REDUNDANCY_STRESS = "false_redundancy_stress"
    FEEDBACK_LOOP          = "feedback_loop"
    CHOKEPOINT_SATURATION  = "chokepoint_saturation"
    TEMPORAL_TRAP          = "temporal_trap"
    ASSUMPTION_EROSION     = "assumption_erosion"
    AUTHORITY_VACUUM       = "authority_vacuum"
    VENDOR_FRAGILITY       = "vendor_fragility"


@dataclass
class SignatureMatch:
    signature: SignatureType
    node_id: str
    node_label: str
    confidence: float           # 0–1
    lead_time_hours: float      # estimated time before failure
    failure_mode: str
    evidence: list[str]         # what specific signals fired
    severity: str               # low | medium | high | critical


@dataclass
class PrecursorReport:
    active_signatures: list[SignatureMatch]
    highest_severity: str
    total_active: int
    nodes_at_risk: list[str]
    composite_warning_level: float  # 0-1
    narrative: str


# ──────────────────────────────────────────────────────────────────────────────
# Detection helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_trend(readings: list[NodeStateReading], window: int = 5) -> float:
    """Average load change per reading in the last `window` readings."""
    if len(readings) < 2:
        return 0.0
    recent = readings[-min(window, len(readings)):]
    deltas = [recent[i].load - recent[i - 1].load for i in range(1, len(recent))]
    return sum(deltas) / len(deltas) if deltas else 0.0


def _reliability_trend(readings: list[NodeStateReading], window: int = 5) -> float:
    """Average reliability change per reading."""
    if len(readings) < 2:
        return 0.0
    recent = readings[-min(window, len(readings)):]
    deltas = [recent[i].reliability - recent[i - 1].reliability for i in range(1, len(recent))]
    return sum(deltas) / len(deltas) if deltas else 0.0


def _is_monotone_declining(values: list[float], threshold: int = 4) -> bool:
    """True if the last `threshold` values are consistently declining."""
    if len(values) < threshold:
        return False
    recent = values[-threshold:]
    return all(recent[i] <= recent[i - 1] for i in range(1, len(recent)))


def _oscillation_index(values: list[float]) -> float:
    """Measures oscillation: high = back-and-forth pattern."""
    if len(values) < 4:
        return 0.0
    sign_changes = sum(
        1 for i in range(2, len(values))
        if (values[i] - values[i-1]) * (values[i-1] - values[i-2]) < 0
    )
    return sign_changes / (len(values) - 2)


# ──────────────────────────────────────────────────────────────────────────────
# Signature definitions
# ──────────────────────────────────────────────────────────────────────────────

class PrecursorLibrary:
    """
    Library of precursor signatures. Each detect_* method returns
    (detected: bool, confidence: float, evidence: list[str]).
    """

    def detect_velocity_spike(
        self,
        node_id: str,
        readings: list[NodeStateReading],
        proximity: Optional[ProximityScore] = None,
    ) -> tuple[bool, float, list[str]]:
        """Rapid acceleration in load rate — indicates stress building faster than expected."""
        if len(readings) < 4:
            return False, 0.0, []
        trend = _load_trend(readings, window=4)
        acc_trend = _load_trend(readings, window=8)
        evidence = []
        if trend > 0.04:  # >4% per reading
            evidence.append(f"load rate +{trend:.1%}/reading")
        if trend > acc_trend * 1.5 and trend > 0.02:
            evidence.append("acceleration exceeds recent average by 50%")
        if proximity and proximity.load_rate_per_hour > 0.02:
            evidence.append(f"hourly rate: +{proximity.load_rate_per_hour:.3f}/hr")
        detected = trend > 0.03 or (trend > 0.015 and trend > acc_trend * 1.5)
        confidence = min(0.9, abs(trend) * 20) if detected else 0.0
        return detected, confidence, evidence

    def detect_reliability_decay(
        self,
        node_id: str,
        readings: list[NodeStateReading],
        proximity: Optional[ProximityScore] = None,
    ) -> tuple[bool, float, list[str]]:
        """Steady monotonic reliability decline — often invisible until critical."""
        if len(readings) < 4:
            return False, 0.0, []
        rel_values = [r.reliability for r in readings]
        evidence = []
        is_mono = _is_monotone_declining(rel_values, threshold=4)
        trend = _reliability_trend(readings, window=6)
        if is_mono:
            evidence.append("reliability declining monotonically")
        if trend < -0.02:
            evidence.append(f"reliability rate: {trend:.3f}/reading")
        if proximity and proximity.reliability_headroom < 0.2:
            evidence.append(f"reliability headroom: {proximity.reliability_headroom:.2f}")
        detected = is_mono or trend < -0.02
        confidence = min(0.85, abs(trend) * 15 + (0.3 if is_mono else 0.0)) if detected else 0.0
        return detected, confidence, evidence

    def detect_cascade_primer(
        self,
        node_id: str,
        graph: Graph,
        all_proximity: dict[str, ProximityScore],
    ) -> tuple[bool, float, list[str]]:
        """
        Cluster of medium-stress connected nodes — individually non-critical,
        collectively primed for cascade.
        """
        import networkx as nx
        G = nx.DiGraph()
        for n in graph.nodes:
            G.add_node(n.id)
        for e in graph.edges:
            G.add_edge(e.source, e.target)

        evidence = []
        neighbors = list(G.successors(node_id)) + list(G.predecessors(node_id))
        stressed_neighbors = [
            n for n in neighbors
            if n in all_proximity and all_proximity[n].current_stress > 0.4
        ]
        if len(stressed_neighbors) >= 2:
            evidence.append(f"{len(stressed_neighbors)} stressed neighbors (stress > 0.4)")
        node_stress = all_proximity.get(node_id)
        if node_stress and node_stress.current_stress > 0.35:
            evidence.append(f"node stress: {node_stress.current_stress:.2f}")
        detected = len(stressed_neighbors) >= 2 and bool(node_stress and node_stress.current_stress > 0.3)
        confidence = min(0.75, len(stressed_neighbors) * 0.15) if detected else 0.0
        return detected, confidence, evidence

    def detect_assumption_erosion(
        self,
        node_id: str,
        graph: Graph,
        readings: list[NodeStateReading],
    ) -> tuple[bool, float, list[str]]:
        """Assumption/confidence node showing sustained confidence decay."""
        node = next((n for n in graph.nodes if n.id == node_id), None)
        if not node:
            return False, 0.0, []
        is_assumption = node.node_type == NodeType.ASSUMPTION
        evidence = []
        low_confidence = node.attributes.confidence < 0.5
        low_visibility = node.attributes.visibility < 0.4
        rel_trend = _reliability_trend(readings, window=5) if len(readings) >= 3 else 0.0
        if is_assumption:
            evidence.append("node is an assumption type")
        if low_confidence:
            evidence.append(f"confidence: {node.attributes.confidence:.2f}")
        if low_visibility:
            evidence.append(f"visibility: {node.attributes.visibility:.2f}")
        if rel_trend < -0.02:
            evidence.append(f"confidence declining: {rel_trend:.3f}/reading")
        detected = (is_assumption and low_confidence) or (low_confidence and low_visibility)
        confidence = 0.7 if detected and is_assumption else (0.5 if detected else 0.0)
        return detected, confidence, evidence

    def detect_authority_vacuum(
        self,
        node_id: str,
        graph: Graph,
        readings: list[NodeStateReading],
        all_proximity: dict[str, ProximityScore],
    ) -> tuple[bool, float, list[str]]:
        """Person/team nodes with spiking load and no viable escalation path."""
        import networkx as nx
        node = next((n for n in graph.nodes if n.id == node_id), None)
        if not node or node.node_type not in (NodeType.PERSON, NodeType.TEAM):
            return False, 0.0, []
        G = nx.DiGraph()
        for n in graph.nodes:
            G.add_node(n.id)
        for e in graph.edges:
            G.add_edge(e.source, e.target)

        evidence = []
        proximity = all_proximity.get(node_id)
        load_spike = proximity and proximity.current_load > 0.75
        load_trend = _load_trend(readings, window=4)

        # Check for escalation paths (PERSON nodes that can receive escalations)
        escalation_targets = [
            s for s in G.successors(node_id)
            if any(n.node_type in (NodeType.PERSON, NodeType.TEAM)
                   for n in graph.nodes if n.id == s)
        ]
        no_escalation = len(escalation_targets) == 0

        if load_spike:
            evidence.append(f"high load: {proximity.current_load:.2f}")
        if load_trend > 0.025:
            evidence.append(f"load trend: +{load_trend:.3f}/reading")
        if no_escalation:
            evidence.append("no escalation path available")
        detected = load_spike and no_escalation
        confidence = min(0.80, (0.4 if no_escalation else 0.0) + (0.4 if load_spike else 0.0))
        return detected, confidence, evidence

    def detect_vendor_fragility(
        self,
        node_id: str,
        graph: Graph,
        readings: list[NodeStateReading],
    ) -> tuple[bool, float, list[str]]:
        """External/vendor nodes showing reliability degradation."""
        node = next((n for n in graph.nodes if n.id == node_id), None)
        if not node or node.node_type != NodeType.VENDOR:
            return False, 0.0, []
        evidence = []
        rel_trend = _reliability_trend(readings, window=5) if len(readings) >= 3 else 0.0
        low_replaceability = node.attributes.replaceability < 0.3
        rel_values = [r.reliability for r in readings[-5:]] if len(readings) >= 3 else []
        is_declining = _is_monotone_declining(rel_values, threshold=3) if rel_values else False

        if rel_trend < -0.015:
            evidence.append(f"reliability declining: {rel_trend:.3f}/reading")
        if low_replaceability:
            evidence.append(f"replaceability: {node.attributes.replaceability:.2f}")
        if is_declining:
            evidence.append("monotonic reliability decline")
        detected = (rel_trend < -0.015 or is_declining) and low_replaceability
        confidence = min(0.85, abs(rel_trend) * 20 + (0.2 if is_declining else 0.0)) if detected else 0.0
        return detected, confidence, evidence

    def detect_chokepoint_saturation(
        self,
        node_id: str,
        graph: Graph,
        readings: list[NodeStateReading],
        all_proximity: dict[str, ProximityScore],
    ) -> tuple[bool, float, list[str]]:
        """High-betweenness node approaching load capacity — cascade multiplier."""
        import networkx as nx
        G = nx.DiGraph()
        for n in graph.nodes:
            G.add_node(n.id)
        for e in graph.edges:
            G.add_edge(e.source, e.target)

        evidence = []
        if len(G.nodes) < 3:
            return False, 0.0, []

        try:
            centrality = nx.betweenness_centrality(G, normalized=True)
        except Exception:
            return False, 0.0, []

        node_centrality = centrality.get(node_id, 0.0)
        proximity = all_proximity.get(node_id)
        high_centrality = node_centrality > 0.25
        high_load = proximity and proximity.current_load > 0.70

        if high_centrality:
            evidence.append(f"betweenness centrality: {node_centrality:.3f}")
        if high_load:
            evidence.append(f"load: {proximity.current_load:.2f}")
        detected = high_centrality and bool(high_load)
        confidence = min(0.85, node_centrality * 2 * (proximity.current_load if proximity else 0)) if detected else 0.0
        return detected, confidence, evidence

    def detect_temporal_trap(
        self,
        node_id: str,
        graph: Graph,
    ) -> tuple[bool, float, list[str]]:
        """Time-sensitive node with high load and tight time constraints."""
        node = next((n for n in graph.nodes if n.id == node_id), None)
        if not node:
            return False, 0.0, []
        evidence = []
        high_time_sensitivity = node.attributes.time_sensitivity > 0.7
        high_load = node.attributes.load > 0.65
        low_reversibility = node.attributes.reversibility < 0.3

        if high_time_sensitivity:
            evidence.append(f"time sensitivity: {node.attributes.time_sensitivity:.2f}")
        if high_load:
            evidence.append(f"load: {node.attributes.load:.2f}")
        if low_reversibility:
            evidence.append(f"reversibility: {node.attributes.reversibility:.2f}")
        detected = high_time_sensitivity and high_load
        confidence = min(0.75, node.attributes.time_sensitivity * node.attributes.load) if detected else 0.0
        return detected, confidence, evidence


def _severity_from_confidence(confidence: float, lead_time: float) -> str:
    if lead_time <= 4 or confidence >= 0.8:
        return "critical"
    if lead_time <= 24 or confidence >= 0.6:
        return "high"
    if lead_time <= 72 or confidence >= 0.4:
        return "medium"
    return "low"


def scan_precursors(
    graph: Graph,
    history: dict[str, list[NodeStateReading]],
    all_proximity: dict[str, ProximityScore],
) -> PrecursorReport:
    """
    Scan all nodes in the graph for active precursor signatures.
    """
    lib = PrecursorLibrary()
    matches: list[SignatureMatch] = []

    for node in graph.nodes:
        nid = node.id
        readings = history.get(nid, [])
        proximity = all_proximity.get(nid)

        # Run all applicable detectors
        checks = [
            (SignatureType.VELOCITY_SPIKE,         lib.detect_velocity_spike(nid, readings, proximity),         36.0,  "stress cascade"),
            (SignatureType.RELIABILITY_DECAY,       lib.detect_reliability_decay(nid, readings, proximity),      48.0,  "reliability collapse"),
            (SignatureType.ASSUMPTION_EROSION,      lib.detect_assumption_erosion(nid, graph, readings),         72.0,  "hidden constraint failure"),
            (SignatureType.AUTHORITY_VACUUM,        lib.detect_authority_vacuum(nid, graph, readings, all_proximity), 12.0, "authority vacuum"),
            (SignatureType.VENDOR_FRAGILITY,        lib.detect_vendor_fragility(nid, graph, readings),           24.0,  "vendor dependency failure"),
            (SignatureType.CHOKEPOINT_SATURATION,   lib.detect_chokepoint_saturation(nid, graph, readings, all_proximity), 8.0, "chokepoint cascade"),
            (SignatureType.TEMPORAL_TRAP,           lib.detect_temporal_trap(nid, graph),                        6.0,   "deadline failure"),
            (SignatureType.CASCADE_PRIMER,          lib.detect_cascade_primer(nid, graph, all_proximity),        18.0,  "cascade initiation"),
        ]

        for sig_type, (detected, confidence, evidence), lead_time, failure_mode in checks:
            if detected and confidence >= 0.25:
                matches.append(SignatureMatch(
                    signature=sig_type,
                    node_id=nid,
                    node_label=node.label,
                    confidence=round(confidence, 3),
                    lead_time_hours=lead_time,
                    failure_mode=failure_mode,
                    evidence=evidence,
                    severity=_severity_from_confidence(confidence, lead_time),
                ))

    matches.sort(key=lambda m: (-{"critical": 4, "high": 3, "medium": 2, "low": 1}[m.severity], -m.confidence))

    severity_levels = [m.severity for m in matches]
    highest = "critical" if "critical" in severity_levels else (
              "high" if "high" in severity_levels else (
              "medium" if "medium" in severity_levels else (
              "low" if severity_levels else "none")))

    nodes_at_risk = list(dict.fromkeys(m.node_id for m in matches))
    composite = min(1.0, sum(m.confidence for m in matches) / max(len(graph.nodes), 1))

    narrative = _build_narrative(matches, highest)

    return PrecursorReport(
        active_signatures=matches,
        highest_severity=highest,
        total_active=len(matches),
        nodes_at_risk=nodes_at_risk,
        composite_warning_level=round(composite, 4),
        narrative=narrative,
    )


def _build_narrative(matches: list[SignatureMatch], highest: str) -> str:
    if not matches:
        return "No active precursor signatures detected. System appears stable."
    critical = [m for m in matches if m.severity == "critical"]
    high = [m for m in matches if m.severity == "high"]
    parts = [f"{len(matches)} precursor signature(s) active."]
    if critical:
        labels = ", ".join(f"'{m.node_label}'" for m in critical[:3])
        parts.append(f"Critical: {labels} showing imminent failure signatures.")
    if high:
        labels = ", ".join(f"'{m.node_label}'" for m in high[:3])
        parts.append(f"High: {labels} require immediate monitoring.")
    earliest = min(matches, key=lambda m: m.lead_time_hours)
    parts.append(f"Earliest predicted failure: '{earliest.node_label}' ({earliest.failure_mode}, est. {earliest.lead_time_hours:.0f}h lead time).")
    return " ".join(parts)
