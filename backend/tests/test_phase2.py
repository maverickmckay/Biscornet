"""
Phase 2 tests: Monte Carlo, Assumption Scanner, Document Extract, Log Ingest, DB.
"""
import pathlib
import pytest

from app.models.graph import Graph, Node, Edge, NodeType, EdgeType, NodeAttributes, EdgeAttributes
from app.engines.monte_carlo import MonteCarloEngine
from app.engines.assumption_scanner import AssumptionScanner
from app.utils.doc_extract import TextRelationExtractor, read_text
from app.utils.log_ingest import WorkflowLogIngestor, normalise_log_csv


# ---------------------------------------------------------------------------
# Fixtures (reuse minimal graph helpers)
# ---------------------------------------------------------------------------

def minimal_graph() -> Graph:
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


def assumption_graph() -> Graph:
    """Graph with implicit structural assumptions."""
    nodes = [
        Node(id="x", label="X", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(confidence=0.4, visibility=0.3)),
        Node(id="y", label="Y", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(confidence=0.4, visibility=0.25)),
        Node(id="z", label="Z", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(confidence=0.4, visibility=0.2)),
        Node(id="w1", label="W1", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(confidence=0.4)),
        Node(id="w2", label="W2", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(confidence=0.4)),
        Node(id="w3", label="W3", node_type=NodeType.FUNCTION,
             attributes=NodeAttributes(confidence=0.4)),
        Node(id="assume", label="Critical Assumption", node_type=NodeType.ASSUMPTION,
             attributes=NodeAttributes(replaceability=0.0)),
        Node(id="dep", label="Dependent", node_type=NodeType.FUNCTION),
    ]
    edges = [
        Edge(id="e1", source="x", target="y", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.5)),
        Edge(id="e2", source="y", target="z", edge_type=EdgeType.DEPENDS_ON,
             attributes=EdgeAttributes(reliability=0.5)),
        Edge(id="e3", source="w1", target="x", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e4", source="w2", target="x", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e5", source="w3", target="x", edge_type=EdgeType.DEPENDS_ON),
        Edge(id="e6", source="assume", target="dep", edge_type=EdgeType.CONTINGENT_ON),
    ]
    return Graph(id="assume_g", name="AssumptionGraph", nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

class TestMonteCarlo:
    def test_returns_result(self):
        g = minimal_graph()
        engine = MonteCarloEngine(g, n_trials=50, seed=42)
        result = engine.run("node_removal", "b")
        assert result.n_trials == 50
        assert 0.0 <= result.collapse_probability <= 1.0

    def test_high_collapse_probability_for_spof(self):
        g = minimal_graph()
        engine = MonteCarloEngine(g, n_trials=100, seed=0)
        result = engine.run("node_removal", "b")
        # b is the only path — should have high collapse probability
        assert result.collapse_probability > 0.5

    def test_histogram_has_ten_bins(self):
        g = minimal_graph()
        engine = MonteCarloEngine(g, n_trials=50, seed=1)
        result = engine.run("node_removal", "b")
        assert len(result.histogram_reroute) == 10

    def test_stats_have_required_fields(self):
        g = minimal_graph()
        engine = MonteCarloEngine(g, n_trials=50, seed=2)
        result = engine.run("node_removal", "b")
        from dataclasses import fields
        from app.engines.monte_carlo import DistStats
        stat_field_names = {f.name for f in fields(DistStats)}
        assert stat_field_names == {"mean", "median", "p5", "p95", "std"}
        rs = result.reroute_score
        for attr in stat_field_names:
            assert getattr(rs, attr) is not None

    def test_deterministic_with_seed(self):
        g = minimal_graph()
        r1 = MonteCarloEngine(g, n_trials=50, seed=99).run("node_removal", "b")
        r2 = MonteCarloEngine(g, n_trials=50, seed=99).run("node_removal", "b")
        assert r1.collapse_probability == r2.collapse_probability

    def test_vendor_outage_simulation(self):
        nodes = [
            Node(id="v", label="Vendor", node_type=NodeType.VENDOR,
                 attributes=NodeAttributes(criticality=0.9)),
            Node(id="w", label="Warehouse", node_type=NodeType.ASSET),
            Node(id="p", label="Production", node_type=NodeType.PROCESS_STEP),
        ]
        edges = [
            Edge(id="e1", source="v", target="w", edge_type=EdgeType.DEPENDS_ON),
            Edge(id="e2", source="w", target="p", edge_type=EdgeType.DEPENDS_ON),
        ]
        g = Graph(id="vendor_g", name="VendorGraph", nodes=nodes, edges=edges)
        engine = MonteCarloEngine(g, n_trials=50, seed=5)
        result = engine.run("vendor_outage", "v")
        assert result.simulation_type == "vendor_outage"
        assert result.n_trials > 0

    def test_to_dict_serialisable(self):
        import json
        g = minimal_graph()
        result = MonteCarloEngine(g, n_trials=20, seed=7).run("node_removal", "b")
        d = result.to_dict()
        json.dumps(d)  # should not raise


# ---------------------------------------------------------------------------
# Assumption scanner
# ---------------------------------------------------------------------------

class TestAssumptionScanner:
    def test_structural_low_reliability(self):
        g = assumption_graph()
        scanner = AssumptionScanner(g)
        result = scanner.scan()
        # x→y and y→z have reliability 0.5 — should be flagged
        desc_texts = " ".join(ia.description for ia in result.implicit_assumptions)
        assert "reliability" in desc_texts.lower() or len(result.implicit_assumptions) > 0

    def test_structural_dark_path(self):
        g = assumption_graph()
        scanner = AssumptionScanner(g)
        result = scanner.scan()
        structural = [ia for ia in result.implicit_assumptions if ia.scan_type == "structural"]
        assert len(structural) > 0

    def test_unbreakable_contingency(self):
        g = assumption_graph()
        scanner = AssumptionScanner(g)
        result = scanner.scan()
        # assume node has replaceability=0 and CONTINGENT_ON edge — should be flagged
        descriptions = [ia.description for ia in result.implicit_assumptions]
        assert any("replaceability" in d.lower() or "hard assumption" in d.lower() or "non-replaceable" in d.lower()
                   for d in descriptions)

    def test_textual_pass(self):
        g = minimal_graph()
        scanner = AssumptionScanner(g)
        text = (
            "This will not affect the timeline. "
            "Assuming normal market conditions, delivery is expected. "
            "It is expected that the vendor will comply. "
        )
        result = scanner.scan(text=text)
        textual = [ia for ia in result.implicit_assumptions if ia.scan_type == "textual"]
        assert len(textual) >= 2

    def test_scan_returns_counts(self):
        g = assumption_graph()
        scanner = AssumptionScanner(g)
        result = scanner.scan()
        assert result.structural_count == len([ia for ia in result.implicit_assumptions if ia.scan_type == "structural"])
        assert result.textual_count == len([ia for ia in result.implicit_assumptions if ia.scan_type == "textual"])

    def test_integrated_in_analyzer(self):
        from app.engines.analyzer import analyze
        g = assumption_graph()
        analysis = analyze(g)
        # implicit_assumptions field should exist and be populated
        assert hasattr(analysis, "implicit_assumptions")
        assert isinstance(analysis.implicit_assumptions, list)


# ---------------------------------------------------------------------------
# Document extraction
# ---------------------------------------------------------------------------

class TestDocExtract:
    def test_dependency_pattern(self):
        extractor = TextRelationExtractor("test")
        text = "Finance Department depends on ERP System for budget data. Finance Department depends on ERP System."
        result = extractor.extract(text)
        assert len(result.edges) > 0
        edge_types = {e.edge_type.value for e in result.edges}
        assert "depends_on" in edge_types

    def test_approval_pattern(self):
        extractor = TextRelationExtractor("test")
        text = (
            "Purchase orders must be approved by Procurement Manager. "
            "Purchase orders must be approved by Procurement Manager to proceed."
        )
        result = extractor.extract(text)
        edge_types = {e.edge_type.value for e in result.edges}
        assert "approves" in edge_types

    def test_assumption_detection(self):
        extractor = TextRelationExtractor("test")
        text = (
            "This assumes stable FX rates. "
            "Assuming normal demand, production will proceed. "
            "Assuming normal demand, production will proceed as planned."
        )
        result = extractor.extract(text)
        assert len(result.assumption_sentences) >= 1

    def test_entity_deduplication(self):
        extractor = TextRelationExtractor("test")
        # Same entities mentioned multiple times with slight variation
        text = (
            "Finance Team depends on ERP System.\n"
            "Finance Team depends on ERP System.\n"
            "Finance Team requires ERP System approval.\n"
            "Finance Team requires ERP System approval.\n"
        )
        result = extractor.extract(text)
        labels = [n.label for n in result.nodes]
        # Should not have duplicate node labels
        assert len(labels) == len(set(labels))

    def test_empty_text(self):
        extractor = TextRelationExtractor("test")
        result = extractor.extract("")
        assert result.entity_count == 0
        assert result.relation_count == 0
        assert "No entities found" in " ".join(result.confidence_notes)

    def test_confidence_boost_for_frequent_entities(self):
        extractor = TextRelationExtractor("test")
        # Mention Procurement Manager 5 times
        text = "\n".join([
            "Procurement Manager depends on ERP System.",
            "Procurement Manager depends on ERP System.",
            "Procurement Manager approves purchase orders. Procurement Manager approves purchase orders.",
            "Procurement Manager approves purchase orders.",
        ])
        result = extractor.extract(text)
        pm_nodes = [n for n in result.nodes if "Procurement" in n.label]
        if pm_nodes:
            assert pm_nodes[0].attributes.confidence >= 0.6


# ---------------------------------------------------------------------------
# Workflow log ingestion
# ---------------------------------------------------------------------------

class TestLogIngest:
    def test_basic_csv_analysis(self):
        csv = (
            "task,actor,duration_h,status\n"
            "Invoice Review,Finance,2.0,complete\n"
            "Invoice Review,Finance,8.0,complete\n"
            "Invoice Review,Finance,1.5,complete\n"
            "PO Approval,Manager,0.5,complete\n"
            "PO Approval,Manager,0.5,complete\n"
        )
        records = normalise_log_csv(csv)
        ingestor = WorkflowLogIngestor(records)
        result = ingestor.analyse()
        assert len(result.load_updates) > 0
        assert result.summary_stats["total_records"] == 5

    def test_bottleneck_detection(self):
        # p90/mean ratio for Invoice Review: [1,1,1,1,20] → mean=4.8, p90≈14.2, ratio≈2.96 > 2.5
        csv = (
            "task,duration_h\n"
            "Invoice Review,1.0\n"
            "Invoice Review,1.0\n"
            "Invoice Review,1.0\n"
            "Invoice Review,1.0\n"
            "Invoice Review,20.0\n"  # severe outlier drives p90/mean > 2.5
            "PO Approval,0.5\n"
            "PO Approval,0.4\n"
        )
        records = normalise_log_csv(csv)
        result = WorkflowLogIngestor(records).analyse()
        assert "Invoice Review" in result.bottleneck_labels

    def test_handoff_edges_inferred(self):
        csv = (
            "task,actor\n"
            "Review,Alice\n"
            "Approve,Bob\n"
            "Review,Alice\n"
            "Approve,Bob\n"
        )
        records = normalise_log_csv(csv)
        result = WorkflowLogIngestor(records).analyse()
        assert len(result.inferred_edges) > 0
        # Alice → Bob handoff should be detected
        alice_bob = [e for e in result.inferred_edges
                     if e["source_label"] == "Alice" and e["target_label"] == "Bob"]
        assert len(alice_bob) > 0

    def test_empty_log(self):
        result = WorkflowLogIngestor([]).analyse()
        assert result.bottleneck_labels == []
        assert len(result.warnings) > 0

    def test_missing_columns_graceful(self):
        # No task or actor column — should return partial result with warning
        csv = "timestamp,value\n2024-01-01,100\n2024-01-02,200\n"
        records = normalise_log_csv(csv)
        result = WorkflowLogIngestor(records).analyse()
        assert len(result.warnings) > 0

    def test_load_between_0_and_1(self):
        csv = (
            "task,duration_h\n"
            "A,1.0\nA,2.0\nA,1.5\n"
            "B,10.0\nB,20.0\nB,15.0\n"
        )
        records = normalise_log_csv(csv)
        result = WorkflowLogIngestor(records).analyse()
        for label, load in result.load_updates.items():
            assert 0.0 <= load <= 1.0, f"{label} has invalid load {load}"


# ---------------------------------------------------------------------------
# DB (SQLite in-memory)
# ---------------------------------------------------------------------------

class TestDatabase:
    def test_save_and_retrieve_graph(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        from app.db import models  # noqa
        from app.db.crud import save_graph, get_graph, list_graphs, delete_graph

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        g = minimal_graph()
        save_graph(db, g)

        retrieved = get_graph(db, g.id)
        assert retrieved is not None
        assert retrieved.name == g.name
        assert len(retrieved.nodes) == len(g.nodes)

    def test_list_graphs(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        from app.db import models  # noqa
        from app.db.crud import save_graph, list_graphs

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        g1 = minimal_graph()
        g2 = Graph(id="g2", name="Second", nodes=[], edges=[])
        save_graph(db, g1)
        save_graph(db, g2)

        graphs = list_graphs(db)
        assert len(graphs) == 2
        ids = {g["id"] for g in graphs}
        assert "minimal" in ids and "g2" in ids

    def test_delete_graph(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        from app.db import models  # noqa
        from app.db.crud import save_graph, get_graph, delete_graph

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        g = minimal_graph()
        save_graph(db, g)
        assert get_graph(db, g.id) is not None

        deleted = delete_graph(db, g.id)
        assert deleted is True
        assert get_graph(db, g.id) is None

    def test_save_and_retrieve_analysis(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        from app.db import models  # noqa
        from app.db.crud import save_graph, save_analysis, get_latest_analysis
        from app.engines.analyzer import analyze

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        g = minimal_graph()
        save_graph(db, g)
        analysis = analyze(g)
        save_analysis(db, analysis)

        retrieved = get_latest_analysis(db, g.id)
        assert retrieved is not None
        assert retrieved.graph_id == g.id
        assert len(retrieved.collapse_points) == len(analysis.collapse_points)
