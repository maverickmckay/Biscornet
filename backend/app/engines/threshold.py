"""
Threshold Proximity Engine
--------------------------
Answers the timing question: *when* will a fragile node fail?

Takes time-series readings of node state (load, reliability, stress)
and computes:
  - Current distance from failure threshold
  - Rate of change (per hour, trend direction)
  - Projected time-to-threshold at current trajectory
  - Status classification
  - Confidence in the projection

This converts NNM's static structural analysis into a dynamic
early-warning system. Structural fragility tells you the shape;
threshold proximity tells you the velocity.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ThresholdStatus(str, Enum):
    STABLE      = "stable"       # >72h to threshold, low variance
    DRIFTING    = "drifting"     # trending toward threshold, 24-72h
    APPROACHING = "approaching"  # 4-24h to threshold
    CRITICAL    = "critical"     # <4h to threshold
    EXCEEDED    = "exceeded"     # already past threshold


@dataclass
class NodeStateReading:
    """A single time-stamped reading of a node's operational state."""
    timestamp: datetime
    load: float            # 0–1
    reliability: float     # 0–1
    stress: float = 0.0    # computed or observed composite stress 0–1
    source: str = "manual" # manual|telemetry|calibrated


@dataclass
class TrajectoryPoint:
    hours_from_now: float
    projected_load: float
    projected_reliability: float
    confidence: float


@dataclass
class ProximityScore:
    node_id: str
    node_label: str

    # Current state
    current_load: float
    current_reliability: float
    current_stress: float

    # Threshold distances (0 = at threshold, 1 = far from threshold)
    load_headroom: float         # how much load capacity remains
    reliability_headroom: float  # how far from failure reliability

    # Rate of change (positive = worsening)
    load_rate_per_hour: float
    reliability_rate_per_hour: float

    # Time projections
    hours_to_load_threshold: Optional[float]     # None if stable
    hours_to_reliability_threshold: Optional[float]
    hours_to_failure: Optional[float]            # min of both

    # Trajectory
    trajectory: list[TrajectoryPoint]
    status: ThresholdStatus
    confidence: float

    # Alert
    alert_message: Optional[str]


# Configurable thresholds
LOAD_FAILURE_THRESHOLD = 0.90       # load above this = failure zone
RELIABILITY_FAILURE_THRESHOLD = 0.35 # reliability below this = failure zone
MIN_READINGS_FOR_PROJECTION = 3


class ThresholdEngine:
    """
    Computes threshold proximity and timing projections from historical readings.
    """

    def __init__(
        self,
        load_threshold: float = LOAD_FAILURE_THRESHOLD,
        reliability_threshold: float = RELIABILITY_FAILURE_THRESHOLD,
    ):
        self.load_threshold = load_threshold
        self.reliability_threshold = reliability_threshold

    def compute_proximity(
        self,
        node_id: str,
        node_label: str,
        readings: list[NodeStateReading],
    ) -> ProximityScore:
        """
        Compute threshold proximity from a list of historical state readings.
        Readings should be ordered oldest → newest.
        """
        if not readings:
            return self._empty_score(node_id, node_label)

        readings = sorted(readings, key=lambda r: r.timestamp)
        latest = readings[-1]

        current_load = latest.load
        current_reliability = latest.reliability
        current_stress = latest.stress or self._compute_stress(current_load, current_reliability)

        load_headroom = max(0.0, self.load_threshold - current_load)
        reliability_headroom = max(0.0, current_reliability - self.reliability_threshold)

        # Compute rates of change
        load_rate, rel_rate = self._compute_rates(readings)

        # Project time to threshold
        hours_to_load = self._project_hours_to_threshold(
            current_load, load_rate, self.load_threshold, direction="above"
        )
        hours_to_rel = self._project_hours_to_threshold(
            current_reliability, rel_rate, self.reliability_threshold, direction="below"
        )

        # Minimum hours to any failure
        candidates = [h for h in [hours_to_load, hours_to_rel] if h is not None and h > 0]
        hours_to_failure = min(candidates) if candidates else None

        # Check if already exceeded
        already_exceeded = (
            current_load >= self.load_threshold or
            current_reliability <= self.reliability_threshold
        )

        # Status classification
        status = self._classify_status(hours_to_failure, already_exceeded, load_rate, rel_rate)

        # Build trajectory (next 72 hours)
        trajectory = self._build_trajectory(
            current_load, current_reliability, load_rate, rel_rate
        )

        # Confidence based on reading count and consistency
        confidence = self._compute_confidence(readings, load_rate, rel_rate)

        alert = self._build_alert(status, hours_to_failure, node_label)

        return ProximityScore(
            node_id=node_id,
            node_label=node_label,
            current_load=round(current_load, 4),
            current_reliability=round(current_reliability, 4),
            current_stress=round(current_stress, 4),
            load_headroom=round(load_headroom, 4),
            reliability_headroom=round(reliability_headroom, 4),
            load_rate_per_hour=round(load_rate, 6),
            reliability_rate_per_hour=round(rel_rate, 6),
            hours_to_load_threshold=round(hours_to_load, 1) if hours_to_load else None,
            hours_to_reliability_threshold=round(hours_to_rel, 1) if hours_to_rel else None,
            hours_to_failure=round(hours_to_failure, 1) if hours_to_failure else None,
            trajectory=trajectory,
            status=status,
            confidence=round(confidence, 3),
            alert_message=alert,
        )

    def _compute_stress(self, load: float, reliability: float) -> float:
        """Composite stress: high load + low reliability."""
        return min(1.0, load * (1.0 + (1.0 - reliability) * 0.5))

    def _compute_rates(
        self, readings: list[NodeStateReading]
    ) -> tuple[float, float]:
        """Compute hourly rate of change for load and reliability."""
        if len(readings) < 2:
            return 0.0, 0.0

        # Use linear regression over recent readings (last 10)
        recent = readings[-10:]
        n = len(recent)

        if n < 2:
            return 0.0, 0.0

        # Convert timestamps to hours-from-first
        t0 = recent[0].timestamp
        times = [(r.timestamp - t0).total_seconds() / 3600.0 for r in recent]
        loads = [r.load for r in recent]
        rels = [r.reliability for r in recent]

        load_rate = self._linear_slope(times, loads)
        rel_rate = self._linear_slope(times, rels)

        return load_rate, rel_rate

    def _linear_slope(self, xs: list[float], ys: list[float]) -> float:
        """Simple linear regression slope."""
        n = len(xs)
        if n < 2:
            return 0.0
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if abs(denominator) < 1e-10:
            return 0.0
        return numerator / denominator

    def _project_hours_to_threshold(
        self,
        current: float,
        rate_per_hour: float,
        threshold: float,
        direction: str,  # "above" or "below"
    ) -> Optional[float]:
        """Project hours until current value crosses threshold at current rate."""
        if direction == "above":
            # Already exceeded
            if current >= threshold:
                return 0.0
            # Not moving toward threshold
            if rate_per_hour <= 0:
                return None
            return (threshold - current) / rate_per_hour
        else:  # below
            if current <= threshold:
                return 0.0
            if rate_per_hour >= 0:
                return None
            return (current - threshold) / abs(rate_per_hour)

    def _build_trajectory(
        self,
        current_load: float,
        current_reliability: float,
        load_rate: float,
        rel_rate: float,
        horizon_hours: int = 72,
        steps: int = 8,
    ) -> list[TrajectoryPoint]:
        """Project node state at evenly spaced future time points."""
        points = []
        step_size = horizon_hours / steps
        for i in range(1, steps + 1):
            hours = i * step_size
            proj_load = max(0.0, min(1.0, current_load + load_rate * hours))
            proj_rel = max(0.0, min(1.0, current_reliability + rel_rate * hours))
            # Confidence degrades over time
            confidence = max(0.1, 0.9 - (hours / horizon_hours) * 0.7)
            points.append(TrajectoryPoint(
                hours_from_now=round(hours, 1),
                projected_load=round(proj_load, 4),
                projected_reliability=round(proj_rel, 4),
                confidence=round(confidence, 3),
            ))
        return points

    def _classify_status(
        self,
        hours_to_failure: Optional[float],
        already_exceeded: bool,
        load_rate: float,
        rel_rate: float,
    ) -> ThresholdStatus:
        if already_exceeded:
            return ThresholdStatus.EXCEEDED
        if hours_to_failure is None:
            # Check if drifting (consistent worsening direction)
            if load_rate > 0.005 or rel_rate < -0.005:
                return ThresholdStatus.DRIFTING
            return ThresholdStatus.STABLE
        if hours_to_failure <= 4:
            return ThresholdStatus.CRITICAL
        if hours_to_failure <= 24:
            return ThresholdStatus.APPROACHING
        if hours_to_failure <= 72:
            return ThresholdStatus.DRIFTING
        return ThresholdStatus.STABLE

    def _compute_confidence(
        self,
        readings: list[NodeStateReading],
        load_rate: float,
        rel_rate: float,
    ) -> float:
        """Confidence in projections: more readings + consistent trend = higher confidence."""
        n = len(readings)
        reading_confidence = min(0.9, 0.3 + n * 0.08)  # caps at 0.9 with 8+ readings

        # Variance penalty: high variance = lower confidence
        if n >= 3:
            load_vals = [r.load for r in readings[-8:]]
            try:
                variance = statistics.stdev(load_vals)
                variance_penalty = min(0.3, variance * 2)
            except Exception:
                variance_penalty = 0.1
        else:
            variance_penalty = 0.2

        return max(0.1, reading_confidence - variance_penalty)

    def _build_alert(
        self,
        status: ThresholdStatus,
        hours: Optional[float],
        label: str,
    ) -> Optional[str]:
        if status == ThresholdStatus.EXCEEDED:
            return f"'{label}' has exceeded failure threshold — intervention required now."
        if status == ThresholdStatus.CRITICAL:
            h = f"{hours:.1f}h" if hours else "unknown"
            return f"'{label}' will breach failure threshold in approximately {h}."
        if status == ThresholdStatus.APPROACHING:
            h = f"{hours:.0f}h" if hours else "unknown"
            return f"'{label}' is approaching failure threshold (est. {h})."
        if status == ThresholdStatus.DRIFTING:
            return f"'{label}' is trending toward failure — monitor closely."
        return None

    def _empty_score(self, node_id: str, node_label: str) -> ProximityScore:
        return ProximityScore(
            node_id=node_id, node_label=node_label,
            current_load=0.0, current_reliability=1.0, current_stress=0.0,
            load_headroom=1.0, reliability_headroom=1.0,
            load_rate_per_hour=0.0, reliability_rate_per_hour=0.0,
            hours_to_load_threshold=None, hours_to_reliability_threshold=None,
            hours_to_failure=None, trajectory=[],
            status=ThresholdStatus.STABLE, confidence=0.0, alert_message=None,
        )

    def score_all_nodes(
        self,
        graph,
        history: dict[str, list[NodeStateReading]],
    ) -> dict[str, ProximityScore]:
        """
        Score every node in the graph.
        history: node_id → list of NodeStateReadings
        """
        results = {}
        for node in graph.nodes:
            readings = history.get(node.id, [])
            # If no history, synthesize a single reading from current attributes
            if not readings:
                readings = [NodeStateReading(
                    timestamp=datetime.now(timezone.utc),
                    load=node.attributes.load,
                    reliability=1.0,  # assume full reliability if no history
                    source="synthesized",
                )]
            results[node.id] = self.compute_proximity(node.id, node.label, readings)
        return results
