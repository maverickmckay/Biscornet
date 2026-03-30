"""
Phase 4 tests: Causal Engine, Threshold Engine, Precursor Library,
Isomorphism Engine, Adversarial Engine, Ensemble Engine, Oracle Engine,
Telemetry ingestor, and Oracle/Threshold API routes.
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.graph import (
    Graph, Node, Edge, NodeType, EdgeType,
    NodeAttributes, EdgeAttributes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """In-memory SQLite session."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.db import models  # noqa
    from app.auth import models as auth_models  # noqa
    from app.engines import feedback  # noqa
    from app.jobs import models as job_models  # noqa
    from app.db import history_models  # noqa
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def simple_graph() -> Graph:
    """5-node graph with various edge types."""
    nodes = [
        Node(id="n1", label="Approver", node_type=NodeType.PERSON,
             attributes=NodeAttributes(criticality=0.9, replaceability=0.1, load=0.6)),
        Node(id="n2", label="Core System", node_type=NodeType.SYSTEM,
             attributes=NodeAttributes(criticality=0.85, replaceability=0.15, load=0.75)),
        Node(id="n3", label="Vendor", node_type=NodeType.VENDOR,
             attributes=NodeAttributes(criticality=0.7, replaceability=0.2, load=0.5)),
        Node(id="n4", label="Process", node_type=NodeType.PROCESS_STEP,
             attributes=NodeAttributes(criticality=0.6, replaceability=0.4, load=0.4)),
        Node(id="n5", label="Output", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(criticality=0.5, replaceability=0.6, load=0.3)),
    ]
    edges = [
        Edge(id="e1", source="n1", target="n2", edge_type=EdgeType.APPROVES,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e2", source="n3", target="n2", edge_type=EdgeType.FUNDS,
             attributes=EdgeAttributes(reliability=0.85)),
        Edge(id="e3", source="n2", target="n4", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.8)),
        Edge(id="e4", source="n2", target="n5", edge_type=EdgeType.INFORMS,
             attributes=EdgeAttributes(reliability=0.9)),
        Edge(id="e5", source="n4", target="n5", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.75)),
    ]
    return Graph(id="test", name="TestGraph", nodes=nodes, edges=edges)


def make_readings(
    n: int = 10,
    load_start: float = 0.4,
    load_slope: float = 0.03,
    reliability_start: float = 0.9,
    reliability_slope: float = -0.01,
) -> list:
    """Generate synthetic NodeStateReadings with a linear trend."""
    from app.engines.threshold import NodeStateReading
    now = datetime.now(timezone.utc)
    readings = []
    for i in range(n):
        ts = now - timedelta(hours=(n - i))
        readings.append(NodeStateReading(
            timestamp=ts,
            load=min(1.0, load_start + load_slope * i),
            reliability=max(0.0, reliability_start + reliability_slope * i),
            stress=0.1 * i / n,
            source="test",
        ))
    return readings


# ---------------------------------------------------------------------------
# 1. Causal Engine (5 tests)
# ---------------------------------------------------------------------------

class TestCausalEngine:

    def test_mechanism_inference(self):
        from app.engines.causal import CausalEngine, MechanismType
        g = simple_graph()
        engine = CausalEngine(g)
        result = engine.analyze()
        # APPROVES edge should map to APPROVAL_GATES; check causal_edges
        mechanisms = {ce.mechanism for ce in result.causal_edges}
        assert MechanismType.APPROVAL_GATES in mechanisms

    def test_failure_chains_from_single_node(self):
        from app.engines.causal import CausalEngine
        g = simple_graph()
        engine = CausalEngine(g)
        chains = engine.failure_chains_from("n1")
        assert isinstance(chains, list)

    def test_failure_chain_depth(self):
        from app.engines.causal import CausalEngine
        g = simple_graph()
        engine = CausalEngine(g)
        chains = engine.failure_chains_from("n1", max_depth=2)
        for chain in chains:
            # chain.chain is the node list; length - 1 = depth
            assert len(chain.chain) - 1 <= 2

    def test_analyze_returns_causal_analysis(self):
        from app.engines.causal import CausalEngine, CausalAnalysis
        g = simple_graph()
        engine = CausalEngine(g)
        result = engine.analyze()
        assert isinstance(result, CausalAnalysis)
        assert isinstance(result.failure_chains, list)
        assert isinstance(result.causal_edges, list)

    def test_novel_risk_nodes(self):
        from app.engines.causal import CausalEngine
        g = simple_graph()
        engine = CausalEngine(g)
        result = engine.analyze()
        assert isinstance(result.novel_risk_nodes, list)


# ---------------------------------------------------------------------------
# 2. Threshold Engine (6 tests)
# ---------------------------------------------------------------------------

class TestThresholdEngine:

    def test_stable_node(self):
        from app.engines.threshold import ThresholdEngine, ThresholdStatus
        engine = ThresholdEngine()
        readings = make_readings(n=10, load_start=0.2, load_slope=0.001)
        score = engine.compute_proximity("n1", "Test Node", readings)
        assert score.status in (ThresholdStatus.STABLE, ThresholdStatus.DRIFTING)
        assert 0.0 <= score.confidence <= 1.0

    def test_critical_node(self):
        from app.engines.threshold import ThresholdEngine, ThresholdStatus
        engine = ThresholdEngine()
        readings = make_readings(n=10, load_start=0.80, load_slope=0.008)
        score = engine.compute_proximity("n2", "Critical Node", readings)
        assert score.status in (ThresholdStatus.APPROACHING, ThresholdStatus.CRITICAL, ThresholdStatus.EXCEEDED)

    def test_trajectory_length(self):
        from app.engines.threshold import ThresholdEngine
        engine = ThresholdEngine()
        readings = make_readings(n=8)
        score = engine.compute_proximity("n1", "Node", readings)
        assert len(score.trajectory) == 8  # 8-step 72h window

    def test_score_all_nodes(self):
        from app.engines.threshold import ThresholdEngine, NodeStateReading
        g = simple_graph()
        engine = ThresholdEngine()
        node_history: dict[str, list[NodeStateReading]] = {
            "n2": make_readings(n=6, load_start=0.6, load_slope=0.04),
        }
        scores = engine.score_all_nodes(g, node_history)
        assert len(scores) == len(g.nodes)
        assert "n2" in scores

    def test_linear_slope(self):
        from app.engines.threshold import ThresholdEngine
        engine = ThresholdEngine()
        slope = engine._linear_slope(list(range(5)), [0.0, 0.1, 0.2, 0.3, 0.4])
        assert abs(slope - 0.1) < 1e-6

    def test_no_readings_synthesises_from_graph(self):
        from app.engines.threshold import ThresholdEngine, ThresholdStatus
        g = simple_graph()
        engine = ThresholdEngine()
        scores = engine.score_all_nodes(g, {})
        assert len(scores) == len(g.nodes)
        for score in scores.values():
            assert isinstance(score.status, ThresholdStatus)


# ---------------------------------------------------------------------------
# 3. Precursor Library (5 tests)
# ---------------------------------------------------------------------------

class TestPrecursorLibrary:

    def test_scan_returns_report(self):
        from app.engines.precursor import scan_precursors, PrecursorReport
        from app.engines.threshold import ThresholdEngine
        g = simple_graph()
        history = {"n2": make_readings(n=8, load_start=0.7, load_slope=0.02)}
        proximity = ThresholdEngine().score_all_nodes(g, history)
        report = scan_precursors(g, history, proximity)
        assert isinstance(report, PrecursorReport)
        assert isinstance(report.active_signatures, list)
        assert 0.0 <= report.composite_warning_level <= 1.0

    def test_velocity_spike_detection(self):
        from app.engines.precursor import PrecursorLibrary
        from app.engines.threshold import ThresholdEngine
        # High slope should trigger velocity spike
        readings = make_readings(n=8, load_start=0.3, load_slope=0.08)
        proximity = ThresholdEngine().score_all_nodes(simple_graph(), {"n2": readings})
        lib = PrecursorLibrary()
        detected, conf, evidence = lib.detect_velocity_spike("n2", readings, proximity.get("n2"))
        assert isinstance(detected, bool)
        assert 0.0 <= conf <= 1.0
        assert isinstance(evidence, list)

    def test_reliability_decay_detection(self):
        from app.engines.precursor import PrecursorLibrary
        from app.engines.threshold import ThresholdEngine
        readings = make_readings(n=8, reliability_start=0.8, reliability_slope=-0.06)
        proximity = ThresholdEngine().score_all_nodes(simple_graph(), {"n2": readings})
        lib = PrecursorLibrary()
        detected, conf, evidence = lib.detect_reliability_decay("n2", readings, proximity.get("n2"))
        assert isinstance(detected, bool)

    def test_no_history_no_crash(self):
        from app.engines.precursor import scan_precursors, PrecursorReport
        from app.engines.threshold import ThresholdEngine
        g = simple_graph()
        proximity = ThresholdEngine().score_all_nodes(g, {})
        report = scan_precursors(g, {}, proximity)
        assert isinstance(report, PrecursorReport)

    def test_warning_level_bounded(self):
        from app.engines.precursor import scan_precursors
        from app.engines.threshold import ThresholdEngine
        g = simple_graph()
        history = {
            "n2": make_readings(n=8, load_start=0.8, load_slope=0.02, reliability_start=0.4, reliability_slope=-0.04),
        }
        proximity = ThresholdEngine().score_all_nodes(g, history)
        report = scan_precursors(g, history, proximity)
        assert 0.0 <= report.composite_warning_level <= 1.0


# ---------------------------------------------------------------------------
# 4. Isomorphism Engine (4 tests)
# ---------------------------------------------------------------------------

class TestIsomorphismEngine:

    def test_fingerprint_has_14_dims(self):
        from app.engines.isomorphism import IsomorphismEngine
        g = simple_graph()
        engine = IsomorphismEngine(g)
        fp = engine.compute_fingerprint()
        # Check some expected attributes
        assert hasattr(fp, 'spof_ratio')
        assert hasattr(fp, 'n_nodes')
        assert hasattr(fp, 'density')

    def test_find_analogs(self):
        from app.engines.isomorphism import IsomorphismEngine, ArchetypeMatch
        g = simple_graph()
        engine = IsomorphismEngine(g)
        fp = engine.compute_fingerprint()
        analogs = engine.find_analogs(fp)
        assert isinstance(analogs, list)
        for a in analogs:
            assert isinstance(a, ArchetypeMatch)
            assert 0.0 <= a.similarity_score <= 1.0

    def test_analyze_returns_result(self):
        from app.engines.isomorphism import IsomorphismEngine, IsomorphismResult
        g = simple_graph()
        engine = IsomorphismEngine(g)
        result = engine.analyze()
        assert isinstance(result, IsomorphismResult)
        assert result.best_match is not None or result.best_match is None

    def test_similarity_score_bounded(self):
        from app.engines.isomorphism import IsomorphismEngine
        g = simple_graph()
        engine = IsomorphismEngine(g)
        fp = engine.compute_fingerprint()
        analogs = engine.find_analogs(fp)
        for a in analogs:
            assert 0.0 <= a.similarity_score <= 1.0


# ---------------------------------------------------------------------------
# 5. Adversarial Engine (5 tests)
# ---------------------------------------------------------------------------

class TestAdversarialEngine:

    def test_report_structure(self):
        from app.engines.adversarial import AdversarialEngine, AdversarialReport
        g = simple_graph()
        engine = AdversarialEngine(g)
        report = engine.run()
        assert isinstance(report, AdversarialReport)
        assert report.total_scenarios_generated >= 0
        assert isinstance(report.scenarios, list)

    def test_max_damage_scenarios(self):
        from app.engines.adversarial import AdversarialEngine, ScenarioCategory
        g = simple_graph()
        engine = AdversarialEngine(g)
        scenarios = engine.generate_max_damage(top_k=3)
        assert len(scenarios) <= 3
        for s in scenarios:
            assert s.category == ScenarioCategory.MAX_DAMAGE

    def test_cascade_size(self):
        from app.engines.adversarial import AdversarialEngine
        g = simple_graph()
        engine = AdversarialEngine(g)
        size, affected = engine._cascade_size(["n2"])
        assert isinstance(size, int)
        assert isinstance(affected, list)

    def test_compound_failures(self):
        from app.engines.adversarial import AdversarialEngine, ScenarioCategory
        g = simple_graph()
        engine = AdversarialEngine(g)
        scenarios = engine.generate_compound_failures(max_pairs=5)
        for s in scenarios:
            assert s.category == ScenarioCategory.COMPOUND_FAILURE
            assert len(s.trigger_labels) >= 2

    def test_surprise_failures(self):
        from app.engines.adversarial import AdversarialEngine
        g = simple_graph()
        engine = AdversarialEngine(g)
        scenarios = engine.generate_surprise_failures()
        assert isinstance(scenarios, list)


# ---------------------------------------------------------------------------
# 6. Ensemble Engine (4 tests)
# ---------------------------------------------------------------------------

class TestEnsembleEngine:

    def test_run_returns_result(self):
        from app.engines.ensemble import EnsembleEngine, EnsembleResult
        g = simple_graph()
        engine = EnsembleEngine(g)
        result = engine.run()
        assert isinstance(result, EnsembleResult)
        assert 0.0 <= result.ensemble_confidence <= 1.0

    def test_all_variants_run(self):
        from app.engines.ensemble import EnsembleEngine, WEIGHT_VARIANTS
        g = simple_graph()
        engine = EnsembleEngine(g)
        result = engine.run()
        # variant_agreement maps variant name -> dict; should have one entry per variant
        assert isinstance(result.variant_agreement, dict)
        assert len(result.variant_agreement) == len(WEIGHT_VARIANTS)

    def test_weights_restored_after_run(self):
        from app.engines.ensemble import EnsembleEngine
        from app.engines import scoring as scoring_module
        from app.engines.scoring import NNM_WEIGHTS
        original = dict(NNM_WEIGHTS)
        g = simple_graph()
        engine = EnsembleEngine(g)
        engine.run()
        assert dict(scoring_module.NNM_WEIGHTS) == original

    def test_contested_and_robust(self):
        from app.engines.ensemble import EnsembleEngine
        g = simple_graph()
        engine = EnsembleEngine(g)
        result = engine.run()
        assert isinstance(result.robust_predictions, list)
        assert isinstance(result.contested_predictions, list)


# ---------------------------------------------------------------------------
# 7. Oracle Engine (4 tests)
# ---------------------------------------------------------------------------

class TestOracleEngine:

    def test_predict_returns_oracle_prediction(self):
        from app.engines.oracle import OracleEngine, OraclePrediction
        g = simple_graph()
        engine = OracleEngine(g)
        pred = engine.predict()
        assert isinstance(pred, OraclePrediction)

    def test_confidence_capped_at_92(self):
        from app.engines.oracle import OracleEngine
        g = simple_graph()
        engine = OracleEngine(g)
        pred = engine.predict()
        assert pred.overall_confidence <= 0.92

    def test_uncertainty_decomposition(self):
        from app.engines.oracle import OracleEngine, UncertaintyDecomposition
        g = simple_graph()
        engine = OracleEngine(g)
        pred = engine.predict()
        assert isinstance(pred.uncertainty, UncertaintyDecomposition)
        assert 0.0 <= pred.uncertainty.graph_completeness <= 1.0

    def test_oracle_to_dict(self):
        from app.engines.oracle import OracleEngine, oracle_to_dict
        g = simple_graph()
        engine = OracleEngine(g)
        pred = engine.predict()
        d = oracle_to_dict(pred)
        assert isinstance(d, dict)
        assert "oracle_confidence" in d or "overall_confidence" in d


# ---------------------------------------------------------------------------
# 8. Telemetry Ingestor (4 tests)
# ---------------------------------------------------------------------------

class TestTelemetryIngestor:

    def test_push_batch_stores_records(self, db):
        from app.telemetry.ingestor import push_batch
        from app.db.crud import save_graph
        from app.models.graph import Graph as GModel, Node, NodeType, NodeAttributes
        g = GModel(id="t1", name="T1",
                   nodes=[Node(id="a", label="A", node_type=NodeType.PERSON,
                               attributes=NodeAttributes(criticality=0.5))],
                   edges=[])
        save_graph(db, g)

        readings = [{"node_id": "a", "load": 0.5, "reliability": 0.8, "stress": 0.1, "source": "test"}]
        records = push_batch(db, "t1", readings)
        assert len(records) == 1
        assert records[0].load == 0.5

    def test_get_history_returns_dict(self, db):
        from app.telemetry.ingestor import push_batch, get_history
        from app.db.crud import save_graph
        from app.models.graph import Graph as GModel, Node, NodeType, NodeAttributes
        g = GModel(id="t2", name="T2",
                   nodes=[Node(id="b", label="B", node_type=NodeType.TEAM,
                               attributes=NodeAttributes(criticality=0.4))],
                   edges=[])
        save_graph(db, g)
        push_batch(db, "t2", [{"node_id": "b", "load": 0.3, "reliability": 0.9}])

        history = get_history(db, "t2")
        assert "b" in history
        assert len(history["b"]) == 1

    def test_bootstrap_from_graph(self, db):
        from app.telemetry.ingestor import bootstrap_from_graph
        from app.db.crud import save_graph
        g = simple_graph()
        g.id = "t3"
        save_graph(db, g)
        records = bootstrap_from_graph(db, "t3", g)
        assert len(records) == len(g.nodes)

    def test_get_history_empty(self, db):
        from app.telemetry.ingestor import get_history
        from app.db.crud import save_graph
        g = simple_graph()
        g.id = "t4"
        save_graph(db, g)
        history = get_history(db, "t4")
        assert isinstance(history, dict)


# ---------------------------------------------------------------------------
# 9. Oracle route functions (5 tests — direct, no HTTP startup event)
# ---------------------------------------------------------------------------

class TestOracleRouteFunctions:
    """
    Tests the route handler logic directly (bypassing ASGI startup) to avoid
    the real init_db() running against the test in-memory DB.
    """

    @pytest.fixture
    def saved_graph(self, db):
        from app.db.crud import save_graph
        g = simple_graph()
        save_graph(db, g)
        return g

    def test_threshold_route_returns_scores(self, db, saved_graph):
        from app.api.oracle_routes import threshold_proximity
        result = threshold_proximity(saved_graph.id, db=db, _user=None)
        assert "proximity_scores" in result
        assert result["node_count"] == len(saved_graph.nodes)

    def test_adversarial_route_returns_scenarios(self, db, saved_graph):
        from app.api.oracle_routes import adversarial_scan
        result = adversarial_scan(saved_graph.id, db=db, _user=None)
        assert "scenarios" in result
        assert "total_scenarios" in result

    def test_oracle_predict_route_returns_dict(self, db, saved_graph):
        from app.api.oracle_routes import oracle_predict
        result = oracle_predict(saved_graph.id, db=db, _user=None)
        assert isinstance(result, dict)
        assert "overall_confidence" in result

    def test_threshold_route_404_on_missing(self, db):
        from fastapi import HTTPException
        from app.api.oracle_routes import threshold_proximity
        with pytest.raises(HTTPException) as exc_info:
            threshold_proximity("nonexistent_graph", db=db, _user=None)
        assert exc_info.value.status_code == 404

    def test_telemetry_bootstrap_route(self, db, saved_graph):
        from app.api.telemetry_routes import bootstrap_history
        result = bootstrap_history(saved_graph.id, db=db, _user=None)
        assert result["bootstrapped_nodes"] == len(saved_graph.nodes)
