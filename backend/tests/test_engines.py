"""
Unit tests for the core engines.
Run with: pytest backend/tests/
"""
import json
import pathlib
import pytest

from app.models.graph import Graph, Node, Edge, NodeType, EdgeType, NodeAttributes, EdgeAttributes
from app.engines.dependency import DependencyEngine
from app.engines.flow import FlowEngine
from app.engines.scenario import ScenarioEngine
from app.engines.scoring import ScoringEngine
from app.engines.classifier import ActionClassifier
from app.engines.analyzer import analyze
from app.utils.ingest import from_json, from_csv_edge_list


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def minimal_graph() -> Graph:
    """A → B → C with no reroute."""
    nodes = [
        Node(id="a", label="A", node_type=NodeType.FUNCTION),
        Node(id="b", label="B", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(criticality=0.9, replaceability=0.1)),
        Node(id="c", label="C", node_type=NodeType.FUNCTION),
    ]
    edges = [
        Edge(id="e1", source="a", target="b", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e2", source="b", target="c", edge_type=EdgeType.DEPENDS_ON),
    ]
    return Graph(id="minimal", name="Minimal", nodes=nodes, edges=edges)


def redundant_graph() -> Graph:
    """A → B, A → C, B → D, C → D (D has two paths)."""
    nodes = [
        Node(id="a", label="A", node_type=NodeType.FUNCTION),
        Node(id="b", label="B", node_type=NodeType.FUNCTION),
        Node(id="c", label="C", node_type=NodeType.FUNCTION),
        Node(id="d", label="D", node_type=NodeType.FUNCTION),
    ]
    edges = [
        Edge(id="e1", source="a", target="b", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e2", source="a", target="c", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e3", source="b", target="d", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e4", source="c", target="d", edge_type=EdgeType.DEPENDS_ON),
    ]
    return Graph(id="redundant", name="Redundant", nodes=nodes, edges=edges)


def false_redundancy_graph() -> Graph:
    """
    shared → B, shared → C, B → D, C → D
    D has two direct predecessors (B, C) that both share the upstream node 'shared'.
    This is false redundancy: the two paths into D secretly converge on 'shared'.
    """
    nodes = [
        Node(id="shared", label="Shared",  node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(criticality=0.9)),
        Node(id="b", label="B", node_type=NodeType.FUNCTION),
        Node(id="c", label="C", node_type=NodeType.FUNCTION),
        Node(id="d", label="D", node_type=NodeType.FUNCTION),
    ]
    edges = [
        Edge(id="e1", source="shared", target="b", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e2", source="shared", target="c", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e3", source="b", target="d", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e4", source="c", target="d", edge_type=EdgeType.DEPENDS_ON),
    ]
    return Graph(id="false_red", name="FalseRedundancy", nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Dependency engine
# ---------------------------------------------------------------------------

class TestDependencyEngine:
    def test_spof_detected(self):
        g = minimal_graph()
        dep = DependencyEngine(g)
        spofs = dep.single_points_of_failure()
        assert "b" in spofs

    def test_no_spof_redundant(self):
        g = redundant_graph()
        dep = DependencyEngine(g)
        spofs = dep.single_points_of_failure()
        # 'a' may still be a SPOF (source), but 'b' and 'c' are not
        assert "b" not in spofs
        assert "c" not in spofs

    def test_reroute_blocked(self):
        g = minimal_graph()
        dep = DependencyEngine(g)
        score = dep.reroute_availability("b")
        assert score == 0.0

    def test_reroute_available(self):
        g = redundant_graph()
        dep = DependencyEngine(g)
        score = dep.reroute_availability("b")
        assert score > 0.0

    def test_false_redundancy_detected(self):
        g = false_redundancy_graph()
        dep = DependencyEngine(g)
        fr = dep.false_redundancy_score("d")
        assert fr > 0.0

    def test_downstream_cascade(self):
        g = minimal_graph()
        dep = DependencyEngine(g)
        cascade = dep.downstream_cascade("a")
        assert "b" in cascade
        assert "c" in cascade

    def test_dead_ends(self):
        g = minimal_graph()
        dep = DependencyEngine(g)
        dead = dep.dead_ends()
        # 'c' is the sink (no outgoing edges, has incoming), 'a' is source
        assert "c" in dead


# ---------------------------------------------------------------------------
# Flow engine
# ---------------------------------------------------------------------------

class TestFlowEngine:
    def test_timing_trap_detected(self):
        nodes = [
            Node(id="s", label="S", node_type=NodeType.FUNCTION),
            Node(id="t", label="T", node_type=NodeType.FUNCTION),
        ]
        edges = [
            Edge(id="e1", source="s", target="t", edge_type=EdgeType.TIMED_BEFORE,
                 attributes=EdgeAttributes(latency=48.0)),
        ]
        g = Graph(id="tt", name="TimingTrap", nodes=nodes, edges=edges)
        flow = FlowEngine(g)
        issues = flow.timing_traps(deadline_hours=24.0)
        assert len(issues) > 0
        assert issues[0].kind == "timing_trap"

    def test_no_timing_trap_fast_path(self):
        nodes = [
            Node(id="s", label="S", node_type=NodeType.FUNCTION),
            Node(id="t", label="T", node_type=NodeType.FUNCTION),
        ]
        edges = [
            Edge(id="e1", source="s", target="t", edge_type=EdgeType.TIMED_BEFORE,
                 attributes=EdgeAttributes(latency=2.0)),
        ]
        g = Graph(id="fast", name="Fast", nodes=nodes, edges=edges)
        flow = FlowEngine(g)
        issues = flow.timing_traps(deadline_hours=24.0)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Scenario engine
# ---------------------------------------------------------------------------

class TestScenarioEngine:
    def test_node_removal_no_reroute(self):
        g = minimal_graph()
        se = ScenarioEngine(g)
        result = se.node_removal("b")
        assert result.reroute_score == 0.0
        assert not result.is_reroutable

    def test_node_removal_with_reroute(self):
        g = redundant_graph()
        se = ScenarioEngine(g)
        result = se.node_removal("b")
        assert result.reroute_score > 0.0
        assert result.is_reroutable

    def test_vendor_outage(self):
        nodes = [
            Node(id="v", label="Vendor", node_type=NodeType.VENDOR,
                 attributes=NodeAttributes(criticality=0.9)),
            Node(id="w", label="Warehouse", node_type=NodeType.ASSET),
        ]
        edges = [Edge(id="e1", source="v", target="w", edge_type=EdgeType.DEPENDS_ON)]
        g = Graph(id="v_test", name="Vendor", nodes=nodes, edges=edges)
        se = ScenarioEngine(g)
        result = se.vendor_outage("v")
        assert result.simulation_type == "vendor_outage"


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

class TestScoringEngine:
    def test_high_score_for_spof(self):
        g = minimal_graph()
        scoring = ScoringEngine(g)
        scores = scoring.score_node("b")
        # b is the only path from a to c — must score above source node a
        assert scores["nnm_score"] > scoring.score_node("a")["nnm_score"]
        assert scores["nnm_score"] > 0.1

    def test_lower_score_for_redundant_path(self):
        g = redundant_graph()
        scoring = ScoringEngine(g)
        score_b = scoring.score_node("b")["nnm_score"]
        g2 = minimal_graph()
        scoring2 = ScoringEngine(g2)
        score_b2 = scoring2.score_node("b")["nnm_score"]
        # Redundant graph b should have lower NNM than choke-point b
        assert score_b < score_b2

    def test_score_all_returns_all_nodes(self):
        g = minimal_graph()
        scoring = ScoringEngine(g)
        all_scores = scoring.score_all()
        assert set(all_scores.keys()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Full analysis
# ---------------------------------------------------------------------------

class TestAnalyzer:
    def test_analyze_minimal(self):
        g = minimal_graph()
        result = analyze(g)
        assert result.graph_id == "minimal"
        assert len(result.collapse_points) > 0
        # b is the structural bottleneck — must appear in collapse points
        cp_ids = [cp.node_id for cp in result.collapse_points]
        assert "b" in cp_ids

    def test_analyze_demo_graph(self):
        demo_path = pathlib.Path(__file__).parent.parent.parent / "data" / "samples" / "supply_chain_demo.json"
        g = from_json(demo_path.read_bytes())
        result = analyze(g)
        assert len(result.collapse_points) > 0
        assert result.summary != ""

    def test_action_distribution(self):
        g = minimal_graph()
        result = analyze(g)
        actions = {a["action"] for a in result.top_actions}
        assert len(actions) > 0


# ---------------------------------------------------------------------------
# Ingest utilities
# ---------------------------------------------------------------------------

class TestIngest:
    def test_csv_ingest(self):
        csv = "source_id,target_id,edge_type\na,b,depends_on\nb,c,depends_on\n"
        g = from_csv_edge_list(csv, "Test")
        assert len(g.nodes) == 3
        assert len(g.edges) == 2

    def test_json_round_trip(self):
        g = minimal_graph()
        raw = g.model_dump_json()
        g2 = from_json(raw)
        assert g2.name == g.name
        assert len(g2.nodes) == len(g.nodes)
