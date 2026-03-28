"""
Core graph data models for No Next Move.
Everything in the system maps to nodes and edges.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    PERSON = "person"
    TEAM = "team"
    FUNCTION = "function"
    PROCESS_STEP = "process_step"
    SYSTEM = "system"
    CONTRACT_CLAUSE = "contract_clause"
    VENDOR = "vendor"
    ASSET = "asset"
    DECISION_GATE = "decision_gate"
    ASSUMPTION = "assumption"
    NARRATIVE = "narrative"


class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"
    APPROVES = "approves"
    FUNDS = "funds"
    INFORMS = "informs"
    BLOCKS = "blocks"
    SUBSTITUTES = "substitutes"
    ESCALATES_TO = "escalates_to"
    GOVERNED_BY = "governed_by"
    TIMED_BEFORE = "timed_before"
    CONTINGENT_ON = "contingent_on"


class ActionLabel(str, Enum):
    FIX = "fix"
    MONITOR = "monitor"
    AVOID = "avoid"
    HEDGE = "hedge"
    ESCALATE = "escalate"
    STRESS_TEST = "stress_test"
    EXPLOIT_LAWFUL = "exploit_lawful"


class CollapseRisk(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Node model
# ---------------------------------------------------------------------------

class NodeAttributes(BaseModel):
    criticality: float = Field(0.5, ge=0.0, le=1.0, description="How critical is this node to overall system function")
    time_sensitivity: float = Field(0.5, ge=0.0, le=1.0, description="How time-sensitive is this node's availability")
    replaceability: float = Field(0.5, ge=0.0, le=1.0, description="How easy is it to replace/reroute around this node")
    reversibility: float = Field(0.5, ge=0.0, le=1.0, description="How reversible is a failure at this node")
    load: float = Field(0.5, ge=0.0, le=1.0, description="Current load fraction (0=idle, 1=at capacity)")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence in the data for this node")
    visibility: float = Field(1.0, ge=0.0, le=1.0, description="How visible is this node's state to observers")
    evidence_source: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Node(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    node_type: NodeType
    attributes: NodeAttributes = Field(default_factory=NodeAttributes)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Edge model
# ---------------------------------------------------------------------------

class EdgeAttributes(BaseModel):
    weight: float = Field(1.0, ge=0.0, description="Dependency weight / flow volume")
    latency: float = Field(0.0, ge=0.0, description="Delay in the relationship (e.g. approval lag, hours)")
    reliability: float = Field(1.0, ge=0.0, le=1.0, description="Probability that this edge is active")
    reversible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    target: str
    edge_type: EdgeType
    attributes: EdgeAttributes = Field(default_factory=EdgeAttributes)


# ---------------------------------------------------------------------------
# Graph container
# ---------------------------------------------------------------------------

class Graph(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Analysis results
# ---------------------------------------------------------------------------

class CollapsePoint(BaseModel):
    node_id: str
    node_label: str
    node_type: NodeType
    nnm_score: float = Field(description="No Next Move score 0-1")
    hidden_constraint_score: float = Field(0.0)
    false_redundancy_score: float = Field(0.0)
    pressure_absorption_score: float = Field(0.0)
    reversion_potential_score: float = Field(0.0)
    collapse_risk: CollapseRisk
    action: ActionLabel
    action_rationale: str
    downstream_failures: list[str] = Field(default_factory=list)
    reversion_targets: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class GraphAnalysis(BaseModel):
    graph_id: str
    graph_name: str
    collapse_points: list[CollapsePoint] = Field(default_factory=list)
    hidden_assumptions: list[str] = Field(default_factory=list)
    implicit_assumptions: list[dict] = Field(
        default_factory=list,
        description="Richer implicit assumption objects from AssumptionScanner",
    )
    false_redundancies: list[dict] = Field(default_factory=list)
    top_actions: list[dict] = Field(default_factory=list)
    summary: str = ""
    node_scores: dict[str, dict] = Field(default_factory=dict)
