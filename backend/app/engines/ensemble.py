"""
Ensemble Reasoning Engine
--------------------------
Runs NNM analysis multiple times with different weight configurations
and surfaces where predictions are robust vs where they disagree.

When multiple independent reasoning chains agree on a prediction,
confidence is high. When they disagree, that disagreement IS the signal:
the situation is genuinely uncertain along those dimensions.

This converts false confidence (a single analysis saying "I'm sure")
into calibrated confidence (5 analyses saying "we all agree" or
"we disagree here and here is the range").

Weight variants:
  BASE          — standard NNM weights (0.35/0.20/0.20/0.15/0.10)
  REROUTE_HEAVY — emphasizes reroute failure (connectivity-critical systems)
  TIME_CRITICAL — emphasizes time_to_failure (deadline-sensitive systems)
  HIDDEN_FOCUS  — emphasizes hidden constraints (assumption-heavy systems)
  EVEN          — equal weights (unbiased baseline)
  DEPENDENCY    — emphasizes dependency concentration (hub-spoke systems)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.graph import Graph, GraphAnalysis
from app.engines.scoring import NNM_WEIGHTS, ScoringEngine
from app.engines.analyzer import analyze
from app.engines.classifier import classify_action


WEIGHT_VARIANTS = {
    "base": dict(NNM_WEIGHTS),
    "reroute_heavy": {
        "reroute_failure":          0.55,
        "time_to_failure":          0.15,
        "dependency_concentration": 0.15,
        "return_loop_absence":      0.10,
        "hidden_constraint":        0.05,
    },
    "time_critical": {
        "reroute_failure":          0.20,
        "time_to_failure":          0.45,
        "dependency_concentration": 0.15,
        "return_loop_absence":      0.15,
        "hidden_constraint":        0.05,
    },
    "hidden_focus": {
        "reroute_failure":          0.20,
        "time_to_failure":          0.15,
        "dependency_concentration": 0.15,
        "return_loop_absence":      0.10,
        "hidden_constraint":        0.40,
    },
    "even": {
        "reroute_failure":          0.20,
        "time_to_failure":          0.20,
        "dependency_concentration": 0.20,
        "return_loop_absence":      0.20,
        "hidden_constraint":        0.20,
    },
    "dependency": {
        "reroute_failure":          0.25,
        "time_to_failure":          0.10,
        "dependency_concentration": 0.45,
        "return_loop_absence":      0.10,
        "hidden_constraint":        0.10,
    },
}


@dataclass
class NodeRanking:
    node_id: str
    node_label: str
    scores_by_variant: dict[str, float]  # variant_name → nnm_score
    mean_score: float
    score_variance: float
    rank_variance: int      # how much rank changes across variants
    is_robust: bool         # True if consistently high/low across all variants
    disagreement_axes: list[str]  # which weight dimensions cause disagreement


@dataclass
class EnsembleResult:
    node_rankings: list[NodeRanking]
    robust_predictions: list[str]      # node_ids consistently flagged
    contested_predictions: list[str]   # node_ids where variants disagree
    hidden_by_base: list[str]          # node_ids missed by base but caught by some variants
    ensemble_confidence: float         # 0-1, how much variants agree overall
    variant_agreement: dict[str, float]  # per-variant agreement with ensemble median
    narrative: str


class EnsembleEngine:
    """
    Runs multi-variant analysis and quantifies prediction uncertainty.
    """

    def __init__(self, graph: Graph):
        self.graph = graph

    def _score_with_weights(self, weights: dict) -> dict[str, float]:
        """Score all nodes using a specific weight configuration."""
        import app.engines.scoring as scoring_module
        original = dict(scoring_module.NNM_WEIGHTS)
        scoring_module.NNM_WEIGHTS.update(weights)
        try:
            engine = ScoringEngine(self.graph)
            scores = {n.id: engine.nnm_score(n.id) for n in self.graph.nodes}
        finally:
            scoring_module.NNM_WEIGHTS.clear()
            scoring_module.NNM_WEIGHTS.update(original)
        return scores

    def run(self) -> EnsembleResult:
        """Run all weight variants and compute ensemble statistics."""
        # Collect scores for each variant
        all_variant_scores: dict[str, dict[str, float]] = {}
        for variant_name, weights in WEIGHT_VARIANTS.items():
            all_variant_scores[variant_name] = self._score_with_weights(weights)

        # Build per-node rankings
        node_rankings: list[NodeRanking] = []
        for node in self.graph.nodes:
            nid = node.id
            variant_scores = {v: all_variant_scores[v].get(nid, 0.0) for v in WEIGHT_VARIANTS}
            scores_list = list(variant_scores.values())
            mean_score = sum(scores_list) / len(scores_list)
            variance = (
                sum((s - mean_score) ** 2 for s in scores_list) / len(scores_list)
                if len(scores_list) > 1 else 0.0
            )

            # Compute rank for each variant
            ranks_by_variant: dict[str, int] = {}
            for v, v_scores in all_variant_scores.items():
                sorted_ids = sorted(v_scores.keys(), key=lambda n: -v_scores[n])
                ranks_by_variant[v] = sorted_ids.index(nid) + 1 if nid in sorted_ids else len(sorted_ids)
            rank_variance = max(ranks_by_variant.values()) - min(ranks_by_variant.values())

            # Is the prediction robust?
            is_robust = variance < 0.01 and rank_variance <= 3

            # Which weight dimensions cause disagreement?
            disagreement_axes = []
            base_score = variant_scores.get("base", mean_score)
            if abs(variant_scores.get("reroute_heavy", base_score) - base_score) > 0.08:
                disagreement_axes.append("reroute_failure")
            if abs(variant_scores.get("time_critical", base_score) - base_score) > 0.08:
                disagreement_axes.append("time_to_failure")
            if abs(variant_scores.get("hidden_focus", base_score) - base_score) > 0.08:
                disagreement_axes.append("hidden_constraint")
            if abs(variant_scores.get("dependency", base_score) - base_score) > 0.08:
                disagreement_axes.append("dependency_concentration")

            node_rankings.append(NodeRanking(
                node_id=nid,
                node_label=node.label,
                scores_by_variant=variant_scores,
                mean_score=round(mean_score, 4),
                score_variance=round(variance, 6),
                rank_variance=rank_variance,
                is_robust=is_robust,
                disagreement_axes=disagreement_axes,
            ))

        node_rankings.sort(key=lambda r: -r.mean_score)

        # Identify robust vs contested
        robust_threshold = 0.35
        robust_predictions = [
            r.node_id for r in node_rankings
            if r.is_robust and r.mean_score >= robust_threshold
        ]
        contested_predictions = [
            r.node_id for r in node_rankings
            if not r.is_robust and r.mean_score >= robust_threshold
        ]

        # Nodes hidden by base weights but flagged by specialized variants
        base_threshold = 0.35
        hidden_by_base = [
            r.node_id for r in node_rankings
            if all_variant_scores["base"].get(r.node_id, 0) < base_threshold
            and r.mean_score >= base_threshold
        ]

        # Overall ensemble confidence: mean agreement (1 - normalized variance)
        mean_variances = [r.score_variance for r in node_rankings]
        avg_variance = sum(mean_variances) / len(mean_variances) if mean_variances else 0.0
        ensemble_confidence = round(max(0.0, 1.0 - avg_variance * 20), 4)

        # Per-variant agreement with ensemble median
        medians = {nid: sorted([all_variant_scores[v].get(nid, 0) for v in WEIGHT_VARIANTS])[len(WEIGHT_VARIANTS) // 2]
                   for nid in [n.id for n in self.graph.nodes]}
        variant_agreement = {}
        for v in WEIGHT_VARIANTS:
            diffs = [abs(all_variant_scores[v].get(nid, 0) - medians.get(nid, 0))
                     for nid in medians]
            avg_diff = sum(diffs) / len(diffs) if diffs else 0
            variant_agreement[v] = round(max(0.0, 1.0 - avg_diff * 10), 4)

        narrative = self._build_narrative(
            node_rankings, robust_predictions, contested_predictions,
            hidden_by_base, ensemble_confidence
        )

        return EnsembleResult(
            node_rankings=node_rankings,
            robust_predictions=robust_predictions,
            contested_predictions=contested_predictions,
            hidden_by_base=hidden_by_base,
            ensemble_confidence=ensemble_confidence,
            variant_agreement=variant_agreement,
            narrative=narrative,
        )

    def _build_narrative(
        self,
        rankings: list[NodeRanking],
        robust: list[str],
        contested: list[str],
        hidden: list[str],
        confidence: float,
    ) -> str:
        label_map = {r.node_id: r.node_label for r in rankings}
        parts = [f"Ensemble confidence: {confidence:.0%}."]
        if robust:
            labels = ", ".join(f"'{label_map.get(n, n)}'" for n in robust[:3])
            parts.append(f"Robust predictions (all variants agree): {labels}.")
        if contested:
            labels = ", ".join(f"'{label_map.get(n, n)}'" for n in contested[:3])
            parts.append(f"Contested predictions (variants disagree): {labels} — investigate further.")
        if hidden:
            labels = ", ".join(f"'{label_map.get(n, n)}'" for n in hidden[:3])
            parts.append(f"Hidden by base weights but flagged by specialized analysis: {labels}.")
        return " ".join(parts)
