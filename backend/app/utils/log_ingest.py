"""
Workflow log ingestion.
Accepts CSV/JSON event logs and produces:
  - Bottleneck node IDs (high cycle-time variance or high queue depth)
  - Load calibration updates (dict[node_label, float])
  - Inferred edges (handoff sequences)
  - Summary statistics
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Column name aliases — priority order (first match wins)
_TASK_ALIASES = ["task", "activity", "event_name", "event", "step", "action", "name", "title"]
_ACTOR_ALIASES = ["actor", "user", "owner", "assignee", "responsible", "agent", "performed_by"]
_DURATION_ALIASES = [
    "duration_s", "duration_sec", "duration_seconds",
    "duration_h", "duration_hr", "duration_hours",
    "duration_m", "duration_min", "duration_minutes",
    "duration", "elapsed", "time_taken",
]
_TIMESTAMP_ALIASES = ["timestamp", "start_time", "created_at", "date", "time", "event_time"]
_STATUS_ALIASES = ["status", "state", "result", "outcome"]
_WAIT_STATUSES = {"waiting", "queued", "blocked", "pending", "on hold"}


@dataclass
class ActivityStats:
    label: str
    count: int
    mean_duration: Optional[float]
    p90_duration: Optional[float]
    queue_depth: int
    load: float          # 0-1 heuristic
    is_bottleneck: bool


@dataclass
class LogAnalysisResult:
    bottleneck_labels: list[str]
    load_updates: dict[str, float]      # label → load score
    inferred_edges: list[dict]          # [{source, target, edge_type, count}]
    activity_stats: list[ActivityStats]
    summary_stats: dict
    warnings: list[str] = field(default_factory=list)


def _find_col(headers: list[str], aliases: list[str]) -> Optional[str]:
    hl = [h.lower().strip() for h in headers]
    for alias in aliases:
        if alias in hl:
            return headers[hl.index(alias)]
    return None


def _parse_duration(val: str, col_name: str) -> Optional[float]:
    """Normalise duration to hours."""
    try:
        v = float(val)
    except (ValueError, TypeError):
        return None
    col = col_name.lower()
    if any(x in col for x in ["_s", "sec", "second"]):
        return v / 3600
    if any(x in col for x in ["_m", "min"]):
        return v / 60
    # Default: assume hours
    return v


# Bottleneck threshold: p90/mean ratio
_BOTTLENECK_RATIO = 2.5
# Load formula: load = min(1.0, p90 / (mean * 3)) if p90 and mean exist
_LOAD_SATURATION_FACTOR = 3.0


def normalise_log_csv(raw: str) -> list[dict]:
    """Parse CSV with flexible column detection."""
    reader = csv.DictReader(io.StringIO(raw.strip()))
    return list(reader)


def normalise_log_json(raw: str) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "events" in data:
        return data["events"]
    if isinstance(data, dict) and "records" in data:
        return data["records"]
    return [data]


class WorkflowLogIngestor:
    """Analyse event log records and produce bottleneck + load data."""

    def __init__(self, records: list[dict]):
        self.records = records
        self.warnings: list[str] = []

    def analyse(self) -> LogAnalysisResult:
        if not self.records:
            return LogAnalysisResult([], {}, [], [], {}, ["Empty log — no records."])

        headers = list(self.records[0].keys())
        task_col = _find_col(headers, _TASK_ALIASES)
        actor_col = _find_col(headers, _ACTOR_ALIASES)
        duration_col = _find_col(headers, _DURATION_ALIASES)
        status_col = _find_col(headers, _STATUS_ALIASES)

        if not task_col and not actor_col:
            self.warnings.append("No task or actor column found — bottleneck detection degraded.")

        label_col = task_col or actor_col
        if not label_col:
            return LogAnalysisResult([], {}, [], [], {}, self.warnings)

        # Collect per-activity stats
        activity_durations: dict[str, list[float]] = {}
        activity_queue: dict[str, int] = {}
        activity_count: dict[str, int] = {}

        for row in self.records:
            label = str(row.get(label_col, "")).strip()
            if not label:
                continue
            activity_count[label] = activity_count.get(label, 0) + 1

            if duration_col:
                d = _parse_duration(str(row.get(duration_col, "")), duration_col)
                if d is not None:
                    activity_durations.setdefault(label, []).append(d)

            if status_col:
                status = str(row.get(status_col, "")).lower().strip()
                if status in _WAIT_STATUSES:
                    activity_queue[label] = activity_queue.get(label, 0) + 1

        if not activity_count:
            return LogAnalysisResult([], {}, [], [], {}, self.warnings + ["No labelled activities found."])

        # Normalise counts to load (0-1)
        max_count = max(activity_count.values())

        stats: list[ActivityStats] = []
        load_updates: dict[str, float] = {}
        bottleneck_labels: list[str] = []

        for label, count in activity_count.items():
            durs = activity_durations.get(label, [])
            mean_d: Optional[float] = None
            p90_d: Optional[float] = None
            load: float

            if durs:
                arr = np.array(durs)
                mean_d = float(arr.mean())
                p90_d = float(np.percentile(arr, 90))
                # Load from cycle-time saturation
                load = min(1.0, p90_d / (mean_d * _LOAD_SATURATION_FACTOR + 1e-9))
            else:
                # Frequency-based load
                load = count / max_count

            qd = activity_queue.get(label, 0)
            is_bottleneck = (
                (p90_d is not None and mean_d is not None and mean_d > 0 and p90_d / mean_d > _BOTTLENECK_RATIO)
                or (qd > 0 and qd / count > 0.3)
            )

            if is_bottleneck:
                bottleneck_labels.append(label)

            load_updates[label] = round(load, 4)
            stats.append(ActivityStats(
                label=label,
                count=count,
                mean_duration=round(mean_d, 4) if mean_d is not None else None,
                p90_duration=round(p90_d, 4) if p90_d is not None else None,
                queue_depth=qd,
                load=round(load, 4),
                is_bottleneck=is_bottleneck,
            ))

        stats.sort(key=lambda s: -s.load)

        # Infer handoff edges from sequential actor pairs
        inferred_edges: list[dict] = []
        if actor_col and task_col:
            handoffs: dict[tuple[str, str], int] = {}
            prev_actor: Optional[str] = None
            for row in self.records:
                actor = str(row.get(actor_col, "")).strip()
                if not actor:
                    continue
                if prev_actor and prev_actor != actor:
                    key = (prev_actor, actor)
                    handoffs[key] = handoffs.get(key, 0) + 1
                prev_actor = actor
            for (src, tgt), cnt in sorted(handoffs.items(), key=lambda x: -x[1])[:20]:
                inferred_edges.append({
                    "source_label": src,
                    "target_label": tgt,
                    "edge_type": "timed_before",
                    "count": cnt,
                })

        summary = {
            "total_records": len(self.records),
            "unique_activities": len(activity_count),
            "bottleneck_count": len(bottleneck_labels),
            "has_duration_data": bool(activity_durations),
            "has_status_data": bool(activity_queue),
        }

        return LogAnalysisResult(
            bottleneck_labels=bottleneck_labels,
            load_updates=load_updates,
            inferred_edges=inferred_edges,
            activity_stats=stats,
            summary_stats=summary,
            warnings=self.warnings,
        )
