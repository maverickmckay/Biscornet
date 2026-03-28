"""
Action Classifier
-----------------
Takes per-node scores and node attributes and returns an ActionLabel
with a rationale string.

Decision tree follows the spec:

  Fix          internal + repairable + strategically valuable
  Avoid        external, deep hidden constraints, asymmetric downside
  Hedge        likely survives but stress will hurt; partial exposure
  Monitor      fragile but no active trigger
  Escalate     non-reroutable legal/compliance/leadership dependency
  Stress-test  owned system, reality unclear, need controlled exercise
  Exploit (L)  clear reversion target + public/legal information only
"""
from __future__ import annotations

from app.models.graph import ActionLabel, NodeType, CollapseRisk
from app.engines.scoring import ScoringEngine
from app.models.graph import Graph


# Types that are typically internally controlled
INTERNAL_TYPES = {
    NodeType.PERSON,
    NodeType.TEAM,
    NodeType.FUNCTION,
    NodeType.PROCESS_STEP,
    NodeType.SYSTEM,
    NodeType.DECISION_GATE,
    NodeType.ASSUMPTION,
}

# Types that signal legal/compliance escalation need
LEGAL_TYPES = {
    NodeType.CONTRACT_CLAUSE,
    NodeType.NARRATIVE,
}

# External / hard-to-control types
EXTERNAL_TYPES = {
    NodeType.VENDOR,
    NodeType.ASSET,
}


def classify_action(
    node_type: NodeType,
    nnm_score: float,
    hidden_constraint_score: float,
    false_redundancy_score: float,
    pressure_absorption_score: float,
    reversion_potential_score: float,
    collapse_risk: CollapseRisk,
    replaceability: float,
    reversibility: float,
    confidence: float,
) -> tuple[ActionLabel, str]:
    """
    Returns (ActionLabel, rationale_string).
    """
    # ------------------------------------------------------------------
    # Escalate first — non-reroutable legal/leadership nodes
    # ------------------------------------------------------------------
    if node_type in LEGAL_TYPES and nnm_score >= 0.5:
        return (
            ActionLabel.ESCALATE,
            "Legal or governance node with non-reroutable dependency. "
            "Surface to leadership/legal immediately.",
        )

    if node_type == NodeType.PERSON and nnm_score >= 0.65 and replaceability < 0.3:
        return (
            ActionLabel.ESCALATE,
            "Key-person dependency with no substitute and high collapse score. "
            "Escalate for succession or knowledge-transfer action.",
        )

    # ------------------------------------------------------------------
    # Avoid — external, uncontrollable, asymmetric downside
    # ------------------------------------------------------------------
    if node_type in EXTERNAL_TYPES and nnm_score >= 0.55 and hidden_constraint_score >= 0.4:
        return (
            ActionLabel.AVOID,
            "External node with deep hidden constraints and high fragility. "
            "Exposure is not controllable — avoid dependency increase.",
        )

    if nnm_score >= 0.70 and replaceability < 0.2 and reversibility < 0.2:
        return (
            ActionLabel.AVOID,
            "Extremely fragile node with no reroute and irreversible failure mode. "
            "Do not increase exposure.",
        )

    # ------------------------------------------------------------------
    # Fix — internal, valuable, repairable
    # ------------------------------------------------------------------
    if node_type in INTERNAL_TYPES and nnm_score >= 0.45 and replaceability >= 0.4:
        return (
            ActionLabel.FIX,
            "Internal node with manageable repair cost and identifiable reroute path. "
            "Build redundancy or reduce dependency concentration.",
        )

    # ------------------------------------------------------------------
    # Stress-test — owned system, uncertainty high
    # ------------------------------------------------------------------
    if node_type in INTERNAL_TYPES and confidence < 0.6 and nnm_score >= 0.35:
        return (
            ActionLabel.STRESS_TEST,
            "Internal node with high NNM score but low data confidence. "
            "Run a controlled exercise to validate actual reroute capability.",
        )

    # ------------------------------------------------------------------
    # Hedge — partial external exposure, survivable
    # ------------------------------------------------------------------
    if node_type in EXTERNAL_TYPES and 0.3 <= nnm_score < 0.55:
        return (
            ActionLabel.HEDGE,
            "External node with moderate fragility. "
            "System likely survives but stress events will hurt — offset exposure.",
        )

    if false_redundancy_score >= 0.6 and nnm_score >= 0.4:
        return (
            ActionLabel.HEDGE,
            "False redundancy detected — apparent backup paths converge on a shared bottleneck. "
            "Hedge against simultaneous failure.",
        )

    # ------------------------------------------------------------------
    # Exploit (lawful) — clear reversion target, public information
    # ------------------------------------------------------------------
    if reversion_potential_score >= 0.6 and collapse_risk in (CollapseRisk.HIGH, CollapseRisk.CRITICAL):
        return (
            ActionLabel.EXPLOIT_LAWFUL,
            "Clear reversion targets identified. Value/demand migrates on failure. "
            "Lawful positioning based on publicly available structural analysis.",
        )

    # ------------------------------------------------------------------
    # Monitor — fragile but not acute
    # ------------------------------------------------------------------
    if nnm_score >= 0.20:
        return (
            ActionLabel.MONITOR,
            "Structural weakness present but no active trigger. "
            "Track leading indicators and review if pressure rises.",
        )

    # ------------------------------------------------------------------
    # Default: Monitor
    # ------------------------------------------------------------------
    return (
        ActionLabel.MONITOR,
        "No immediate action required. Continue baseline monitoring.",
    )


class ActionClassifier:
    """Runs the classifier for every node in a scored graph."""

    def __init__(self, graph: Graph, scoring: ScoringEngine):
        self.graph = graph
        self.scoring = scoring
        self._node_map = {n.id: n for n in graph.nodes}

    def classify_node(self, node_id: str) -> tuple[ActionLabel, str]:
        scores = self.scoring.score_node(node_id)
        node = self._node_map.get(node_id)
        if not node:
            return ActionLabel.MONITOR, "Node not found."

        return classify_action(
            node_type=node.node_type,
            nnm_score=scores["nnm_score"],
            hidden_constraint_score=scores["hidden_constraint_score"],
            false_redundancy_score=scores["false_redundancy_score"],
            pressure_absorption_score=scores["pressure_absorption_score"],
            reversion_potential_score=scores["reversion_potential_score"],
            collapse_risk=CollapseRisk(scores["collapse_risk"]),
            replaceability=node.attributes.replaceability,
            reversibility=node.attributes.reversibility,
            confidence=node.attributes.confidence,
        )

    def classify_all(self) -> dict[str, tuple[ActionLabel, str]]:
        return {n.id: self.classify_node(n.id) for n in self.graph.nodes}
