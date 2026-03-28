"""
Analysis Orchestrator
---------------------
Runs all three engines + scoring + classification for a complete graph
and returns a GraphAnalysis result.
"""
from __future__ import annotations

from app.models.graph import Graph, GraphAnalysis, CollapsePoint, NodeType
from app.engines.dependency import DependencyEngine
from app.engines.flow import FlowEngine
from app.engines.scenario import ScenarioEngine
from app.engines.scoring import ScoringEngine
from app.engines.classifier import ActionClassifier
from app.engines.assumption_scanner import AssumptionScanner


def analyze(graph: Graph, raw_text: str | None = None) -> GraphAnalysis:
    dep = DependencyEngine(graph)
    flow = FlowEngine(graph)
    scoring = ScoringEngine(graph)
    classifier = ActionClassifier(graph, scoring)
    assumption_scan = AssumptionScanner(graph).scan(text=raw_text)

    node_scores = scoring.score_all()
    actions = classifier.classify_all()
    spofs = set(dep.single_points_of_failure())
    flow_issues = flow.all_issues()

    # Build flow-issue index by node
    flow_by_node: dict[str, list] = {}
    for issue in flow_issues:
        for nid in issue.node_ids:
            flow_by_node.setdefault(nid, []).append(issue)

    collapse_points: list[CollapsePoint] = []
    for node in graph.nodes:
        nid = node.id
        scores = node_scores[nid]
        action, rationale = actions[nid]

        # Only surface nodes with non-trivial collapse risk
        if scores["nnm_score"] < 0.10 and nid not in spofs:
            continue

        downstream = dep.downstream_cascade(nid)
        reversion = dep.reversion_targets(nid)

        # Build evidence list
        evidence = []
        if nid in spofs:
            evidence.append("Identified as articulation point (SPOF) in structural analysis.")
        for fi in flow_by_node.get(nid, []):
            evidence.append(fi.description)
        if scores["false_redundancy_score"] > 0.4:
            evidence.append(
                f"False redundancy score {scores['false_redundancy_score']:.2f} — "
                "apparent backup paths share a hidden bottleneck."
            )
        if scores["hidden_constraint_score"] > 0.3:
            evidence.append(
                f"Hidden constraint score {scores['hidden_constraint_score']:.2f} — "
                "node is more critical than surface metrics suggest."
            )
        if not evidence:
            evidence.append("Elevated NNM score from dependency concentration or load analysis.")

        node_label_map = {n.id: n.label for n in graph.nodes}
        collapse_points.append(CollapsePoint(
            node_id=nid,
            node_label=node.label,
            node_type=node.node_type,
            nnm_score=scores["nnm_score"],
            hidden_constraint_score=scores["hidden_constraint_score"],
            false_redundancy_score=scores["false_redundancy_score"],
            pressure_absorption_score=scores["pressure_absorption_score"],
            reversion_potential_score=scores["reversion_potential_score"],
            collapse_risk=scores["collapse_risk"],
            action=action,
            action_rationale=rationale,
            downstream_failures=[
                node_label_map.get(i, i)
                for i in downstream[:10]
            ],
            reversion_targets=[
                next((n.label for n in graph.nodes if n.id == t), t)
                for t in reversion[:5]
            ],
            evidence=evidence,
            confidence=node.attributes.confidence,
        ))

    # Sort by NNM score descending
    collapse_points.sort(key=lambda cp: cp.nnm_score, reverse=True)

    # Hidden assumptions: ASSUMPTION nodes with hidden_constraint > 0.3
    hidden_assumptions = [
        n.label
        for n in graph.nodes
        if n.node_type == NodeType.ASSUMPTION
        and node_scores[n.id]["hidden_constraint_score"] > 0.3
    ]
    # Implicit assumptions from structural + textual scan
    implicit_assumptions = [
        {
            "description": ia.description,
            "affected_node_ids": ia.affected_node_ids,
            "scan_type": ia.scan_type,
            "confidence": ia.confidence,
        }
        for ia in assumption_scan.implicit_assumptions
    ]

    # False redundancies summary
    false_reds = [
        {
            "node_id": n.id,
            "node_label": n.label,
            "score": node_scores[n.id]["false_redundancy_score"],
        }
        for n in graph.nodes
        if node_scores[n.id]["false_redundancy_score"] > 0.4
    ]
    false_reds.sort(key=lambda x: -x["score"])

    # Top actions summary
    from collections import Counter
    action_counts = Counter(a.value for _, (a, _) in actions.items())
    top_actions = [
        {"action": k, "count": v}
        for k, v in action_counts.most_common()
    ]

    # Summary text
    critical = [cp for cp in collapse_points if cp.collapse_risk in ("critical", "high")]
    summary = (
        f"Graph '{graph.name}' has {len(graph.nodes)} nodes and {len(graph.edges)} edges. "
        f"{len(collapse_points)} collapse points identified, "
        f"{len(critical)} rated HIGH or CRITICAL. "
        f"{len(spofs)} structural SPOFs detected. "
        f"{len(hidden_assumptions)} hidden assumption nodes. "
        f"{assumption_scan.structural_count} implicit structural assumptions detected."
    )

    return GraphAnalysis(
        graph_id=graph.id,
        graph_name=graph.name,
        collapse_points=collapse_points,
        hidden_assumptions=hidden_assumptions,
        implicit_assumptions=implicit_assumptions,
        false_redundancies=false_reds,
        top_actions=top_actions,
        summary=summary,
        node_scores=node_scores,
    )
