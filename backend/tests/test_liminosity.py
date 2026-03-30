"""
Liminosity integration tests.

Tests prompt builders, graph context formatting, route functions (direct calls),
and signal ingestion. All Claude API calls are mocked — no real API key needed.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph_orm(graph_id="g-lim-1", name="Lim Test"):
    """Minimal ORM-like graph row usable by get_graph."""
    from app.models.graph import Graph, Node, Edge, EdgeType, NodeType
    g = Graph(
        id=graph_id,
        name=name,
        nodes=[
            Node(id="a", label="Auth", node_type=NodeType.SYSTEM),
            Node(id="b", label="DB",   node_type=NodeType.SYSTEM),
            Node(id="c", label="API",  node_type=NodeType.SYSTEM),
        ],
        edges=[
            Edge(source="a", target="b", edge_type=EdgeType.DEPENDS_ON),
            Edge(source="b", target="c", edge_type=EdgeType.DEPENDS_ON),
        ],
    )
    return g


def _make_analysis_json():
    """Minimal serialised GraphAnalysis JSON for context formatting tests."""
    from app.models.graph import GraphAnalysis, CollapsePoint, CollapseRisk, ActionLabel, NodeType
    analysis = GraphAnalysis(
        graph_id="g-lim-1",
        graph_name="Lim Test",
        collapse_points=[
            CollapsePoint(
                node_id="a",
                node_label="Auth",
                node_type=NodeType.SYSTEM,
                nnm_score=0.81,
                collapse_risk=CollapseRisk.HIGH,
                action=ActionLabel.FIX,
                action_rationale="Auth is over-loaded.",
                confidence=0.78,
            ),
        ],
        hidden_assumptions=["Assumption alpha", "Assumption beta"],
        summary="Auth is the primary collapse point.",
    )
    return analysis.model_dump_json()


# ---------------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------------

class TestLayers:

    def test_get_layers_route(self):
        from app.api.liminosity_routes import get_layers
        result = get_layers()
        assert "layers" in result
        assert len(result["layers"]) == 5

    def test_layer_names(self):
        from app.api.liminosity_routes import get_layers, LAYERS
        names = [l["name"] for l in LAYERS]
        assert names == ["permission", "edge", "stakes", "challenge", "field"]

    def test_each_layer_has_prompt(self):
        from app.api.liminosity_routes import LAYERS
        for layer in LAYERS:
            assert "name" in layer
            assert "prompt" in layer
            assert len(layer["prompt"]) > 20


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

class TestEncounterPromptBuilder:

    def test_prompt_contains_layer_name(self):
        from app.api.liminosity_routes import _build_encounter_prompt, LAYERS
        prompt = _build_encounter_prompt("test input", LAYERS[0], [], None)
        assert "PERMISSION" in prompt

    def test_prompt_contains_input(self):
        from app.api.liminosity_routes import _build_encounter_prompt, LAYERS
        prompt = _build_encounter_prompt("my situation here", LAYERS[1], [], None)
        assert "my situation here" in prompt

    def test_prompt_injects_graph_context(self):
        from app.api.liminosity_routes import _build_encounter_prompt, LAYERS
        prompt = _build_encounter_prompt("input", LAYERS[2], [], "GRAPH CONTEXT DATA")
        assert "GRAPH CONTEXT DATA" in prompt
        assert "NNM collapse analysis" in prompt

    def test_prompt_includes_history(self):
        from app.api.liminosity_routes import _build_encounter_prompt, LAYERS, ConversationEntry
        history = [
            ConversationEntry(role="practitioner", content="first message"),
            ConversationEntry(role="liminosity", content="response here"),
        ]
        prompt = _build_encounter_prompt("follow-up", LAYERS[0], history, None)
        assert "first message" in prompt
        assert "PRACTITIONER" in prompt

    def test_prompt_history_truncated_to_six(self):
        from app.api.liminosity_routes import _build_encounter_prompt, LAYERS, ConversationEntry
        # 10 entries — only last 6 should appear
        history = [
            ConversationEntry(role="practitioner", content=f"msg {i}") for i in range(10)
        ]
        prompt = _build_encounter_prompt("q", LAYERS[0], history, None)
        assert "msg 4" in prompt   # entry 4 is within last 6 (4,5,6,7,8,9)
        assert "msg 9" in prompt
        assert "msg 0" not in prompt   # first 4 entries truncated

    def test_prompt_no_history_section_when_empty(self):
        from app.api.liminosity_routes import _build_encounter_prompt, LAYERS
        prompt = _build_encounter_prompt("input", LAYERS[0], [], None)
        assert "Conversation history" not in prompt


class TestSignalPromptBuilder:

    def test_signal_prompt_contains_layer(self):
        from app.api.liminosity_routes import _build_signal_prompt
        prompt = _build_signal_prompt("input", "edge", None)
        assert "edge" in prompt

    def test_signal_prompt_requests_json(self):
        from app.api.liminosity_routes import _build_signal_prompt
        prompt = _build_signal_prompt("situation", "stakes", None)
        assert "perpendicular_question" in prompt
        assert "negative_space" in prompt
        assert "hidden_axis" in prompt
        assert "operative_signal" in prompt
        assert "signature_read" in prompt

    def test_signal_prompt_injects_graph_context(self):
        from app.api.liminosity_routes import _build_signal_prompt
        prompt = _build_signal_prompt("input", "field", "SOME CONTEXT")
        assert "SOME CONTEXT" in prompt

    def test_signal_prompt_no_graph_section_when_none(self):
        from app.api.liminosity_routes import _build_signal_prompt
        prompt = _build_signal_prompt("input", "permission", None)
        assert "Structural context" not in prompt


# ---------------------------------------------------------------------------
# Graph context formatter
# ---------------------------------------------------------------------------

class TestFormatGraphContext:

    def test_context_contains_system_name(self):
        from app.api.liminosity_routes import _format_graph_context
        g = _make_graph_orm(name="MySystem")
        result = _format_graph_context(g, None)
        assert "MySystem" in result

    def test_context_contains_node_count(self):
        from app.api.liminosity_routes import _format_graph_context
        g = _make_graph_orm()
        result = _format_graph_context(g, None)
        assert "3" in result   # 3 nodes

    def test_context_with_analysis_lists_critical_nodes(self):
        from app.api.liminosity_routes import _format_graph_context
        from app.models.graph import GraphAnalysis
        g = _make_graph_orm()
        analysis = GraphAnalysis.model_validate_json(_make_analysis_json())
        result = _format_graph_context(g, analysis)
        assert "Auth" in result
        assert "CRITICAL NODES" in result

    def test_context_with_analysis_includes_hidden_assumptions(self):
        from app.api.liminosity_routes import _format_graph_context
        from app.models.graph import GraphAnalysis
        g = _make_graph_orm()
        analysis = GraphAnalysis.model_validate_json(_make_analysis_json())
        result = _format_graph_context(g, analysis)
        assert "HIDDEN ASSUMPTIONS" in result
        assert "Assumption alpha" in result

    def test_context_with_analysis_includes_summary(self):
        from app.api.liminosity_routes import _format_graph_context
        from app.models.graph import GraphAnalysis
        g = _make_graph_orm()
        analysis = GraphAnalysis.model_validate_json(_make_analysis_json())
        result = _format_graph_context(g, analysis)
        assert "Auth is the primary collapse point" in result

    def test_context_no_analysis_still_returns_string(self):
        from app.api.liminosity_routes import _format_graph_context
        g = _make_graph_orm()
        result = _format_graph_context(g, None)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# get_client helper
# ---------------------------------------------------------------------------

class TestGetClient:

    def test_raises_503_when_no_api_key(self):
        from fastapi import HTTPException
        from app.api.liminosity_routes import _get_client
        from app.config import settings
        original = settings.anthropic_api_key
        settings.anthropic_api_key = ""
        try:
            with pytest.raises(HTTPException) as exc_info:
                _get_client()
            assert exc_info.value.status_code == 503
            assert "ANTHROPIC_API_KEY" in exc_info.value.detail
        finally:
            settings.anthropic_api_key = original


# ---------------------------------------------------------------------------
# Route: GET /graphs/{id}/context
# ---------------------------------------------------------------------------

class TestGetGraphContextRoute:

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()

    @pytest.fixture
    def saved_graph(self, db):
        from app.db import crud
        from app.models.graph import Graph, Node, Edge, EdgeType, NodeType
        g = Graph(
            id="g-ctx-1",
            name="Context Test Graph",
            nodes=[
                Node(id="x", label="X Node", node_type=NodeType.SYSTEM),
                Node(id="y", label="Y Node", node_type=NodeType.SYSTEM),
            ],
            edges=[Edge(source="x", target="y", edge_type=EdgeType.DEPENDS_ON)],
        )
        crud.save_graph(db, g)
        return g

    def test_get_graph_context_returns_context_string(self, db, saved_graph):
        from app.api.liminosity_routes import get_graph_context
        result = get_graph_context(graph_id=saved_graph.id, db=db, _user=None)
        assert result["graph_id"] == saved_graph.id
        assert result["graph_name"] == "Context Test Graph"
        assert isinstance(result["context"], str)
        assert len(result["context"]) > 0

    def test_get_graph_context_404_for_missing(self, db):
        from fastapi import HTTPException
        from app.api.liminosity_routes import get_graph_context
        with pytest.raises(HTTPException) as exc_info:
            get_graph_context(graph_id="nonexistent", db=db, _user=None)
        assert exc_info.value.status_code == 404

    def test_get_graph_context_has_analysis_false_without_analysis(self, db, saved_graph):
        from app.api.liminosity_routes import get_graph_context
        result = get_graph_context(graph_id=saved_graph.id, db=db, _user=None)
        assert result["has_analysis"] is False

    def test_get_graph_context_has_analysis_true_with_analysis(self, db, saved_graph):
        from app.api.liminosity_routes import get_graph_context
        from app.db import crud
        from app.models.graph import GraphAnalysis
        analysis = GraphAnalysis(
            graph_id=saved_graph.id,
            graph_name="Context Test Graph",
            collapse_points=[],
            hidden_assumptions=["Assumption X"],
            summary="Test summary.",
        )
        crud.save_analysis(db, analysis)
        result = get_graph_context(graph_id=saved_graph.id, db=db, _user=None)
        assert result["has_analysis"] is True


# ---------------------------------------------------------------------------
# Route: POST /graphs/{id}/ingest-signals
# ---------------------------------------------------------------------------

class TestIngestSignalsRoute:

    @pytest.fixture
    def db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.database import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()

    @pytest.fixture
    def saved_graph_with_analysis(self, db):
        from app.db import crud
        from app.models.graph import Graph, Node, Edge, EdgeType, NodeType, GraphAnalysis
        g = Graph(
            id="g-ingest-1",
            name="Ingest Test",
            nodes=[
                Node(id="n1", label="Node1", node_type=NodeType.SYSTEM),
                Node(id="n2", label="Node2", node_type=NodeType.SYSTEM),
            ],
            edges=[Edge(source="n1", target="n2", edge_type=EdgeType.DEPENDS_ON)],
        )
        crud.save_graph(db, g)
        analysis = GraphAnalysis(
            graph_id=g.id,
            graph_name="Ingest Test",
            collapse_points=[],
            hidden_assumptions=["Pre-existing assumption"],
            summary="Base analysis.",
        )
        crud.save_analysis(db, analysis)
        return g

    def test_ingest_signals_returns_count(self, db, saved_graph_with_analysis):
        from app.api.liminosity_routes import ingest_signals, IngestSignalsRequest
        req = IngestSignalsRequest(
            hidden_axis="The system optimizes for throughput",
            negative_space="No mention of error states",
            operative_signal="Latency as leverage",
            perpendicular_question="What does the other party actually want?",
        )
        result = ingest_signals(
            graph_id=saved_graph_with_analysis.id,
            req=req,
            db=db,
            _user=None,
        )
        assert result["graph_id"] == saved_graph_with_analysis.id
        assert result["signals_ingested"] == 4

    def test_ingest_signals_stored_in_analysis(self, db, saved_graph_with_analysis):
        from app.api.liminosity_routes import ingest_signals, IngestSignalsRequest
        from app.db.crud import get_latest_analysis
        req = IngestSignalsRequest(hidden_axis="Hidden axis content")
        ingest_signals(
            graph_id=saved_graph_with_analysis.id,
            req=req,
            db=db,
            _user=None,
        )
        analysis = get_latest_analysis(db, saved_graph_with_analysis.id)
        stored = [a for a in analysis.hidden_assumptions if "LIMINOSITY" in a]
        assert len(stored) == 1
        assert "hidden_axis" in stored[0]
        assert "Hidden axis content" in stored[0]

    def test_ingest_signals_preserves_existing_assumptions(self, db, saved_graph_with_analysis):
        from app.api.liminosity_routes import ingest_signals, IngestSignalsRequest
        from app.db.crud import get_latest_analysis
        req = IngestSignalsRequest(operative_signal="The real driver")
        ingest_signals(
            graph_id=saved_graph_with_analysis.id,
            req=req,
            db=db,
            _user=None,
        )
        analysis = get_latest_analysis(db, saved_graph_with_analysis.id)
        assert "Pre-existing assumption" in analysis.hidden_assumptions

    def test_ingest_signals_no_duplicates(self, db, saved_graph_with_analysis):
        from app.api.liminosity_routes import ingest_signals, IngestSignalsRequest
        from app.db.crud import get_latest_analysis
        req = IngestSignalsRequest(hidden_axis="Same axis")
        # Ingest twice
        ingest_signals(saved_graph_with_analysis.id, req, db=db, _user=None)
        ingest_signals(saved_graph_with_analysis.id, req, db=db, _user=None)
        analysis = get_latest_analysis(db, saved_graph_with_analysis.id)
        lim_entries = [a for a in analysis.hidden_assumptions if "[LIMINOSITY:hidden_axis]" in a]
        assert len(lim_entries) == 1   # deduplicated

    def test_ingest_signals_empty_fields_not_stored(self, db, saved_graph_with_analysis):
        from app.api.liminosity_routes import ingest_signals, IngestSignalsRequest
        req = IngestSignalsRequest(hidden_axis="", negative_space="", operative_signal="")
        result = ingest_signals(
            graph_id=saved_graph_with_analysis.id,
            req=req,
            db=db,
            _user=None,
        )
        assert result["signals_ingested"] == 0

    def test_ingest_signals_404_for_missing_graph(self, db):
        from fastapi import HTTPException
        from app.api.liminosity_routes import ingest_signals, IngestSignalsRequest
        req = IngestSignalsRequest(hidden_axis="something")
        with pytest.raises(HTTPException) as exc_info:
            ingest_signals(graph_id="nonexistent", req=req, db=db, _user=None)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Route: POST /encounter — mocked Claude API
# ---------------------------------------------------------------------------

class TestEncounterRoute:

    def _mock_resp(self, text="Encounter response"):
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        resp.usage.input_tokens = 120
        resp.usage.output_tokens = 80
        return resp

    def test_encounter_returns_layer_and_response(self):
        from app.api.liminosity_routes import encounter, EncounterRequest
        from app.config import settings
        settings.anthropic_api_key = "sk-ant-test"
        try:
            with patch("anthropic.Anthropic") as MockCls:
                client = MagicMock()
                MockCls.return_value = client
                client.messages.create.return_value = self._mock_resp("Deep response text")
                req = EncounterRequest(input="What is at stake?", layer_index=2)
                result = encounter(req, _user=None)
                assert result["layer"] == "stakes"
                assert result["response"] == "Deep response text"
                assert "input_tokens" in result
                assert "output_tokens" in result
        finally:
            settings.anthropic_api_key = ""

    def test_encounter_layer_index_clamped(self):
        from app.api.liminosity_routes import encounter, EncounterRequest
        from app.config import settings
        settings.anthropic_api_key = "sk-ant-test"
        try:
            with patch("anthropic.Anthropic") as MockCls:
                client = MagicMock()
                MockCls.return_value = client
                client.messages.create.return_value = self._mock_resp()
                # Layer index 99 should clamp to 4 ("field")
                req = EncounterRequest(input="input", layer_index=99)
                result = encounter(req, _user=None)
                assert result["layer"] == "field"
        finally:
            settings.anthropic_api_key = ""

    def test_encounter_layer_index_negative_clamped(self):
        from app.api.liminosity_routes import encounter, EncounterRequest
        from app.config import settings
        settings.anthropic_api_key = "sk-ant-test"
        try:
            with patch("anthropic.Anthropic") as MockCls:
                client = MagicMock()
                MockCls.return_value = client
                client.messages.create.return_value = self._mock_resp()
                req = EncounterRequest(input="input", layer_index=-5)
                result = encounter(req, _user=None)
                assert result["layer"] == "permission"
        finally:
            settings.anthropic_api_key = ""


# ---------------------------------------------------------------------------
# Route: POST /signal — mocked Claude API
# ---------------------------------------------------------------------------

class TestSignalRoute:

    VALID_SIGNAL_JSON = json.dumps({
        "perpendicular_question": "What do they really want?",
        "negative_space": "They omit all risk discussion.",
        "hidden_axis": "Optimizing for optics, not outcomes.",
        "operative_signal": "Speed signals they have alternatives.",
        "signature_read": "shadow — urgency manufactured.",
    })

    def _mock_resp(self, text=None):
        resp = MagicMock()
        resp.content = [MagicMock(text=text or self.VALID_SIGNAL_JSON)]
        resp.usage.input_tokens = 90
        resp.usage.output_tokens = 60
        return resp

    def test_signal_returns_parsed_json(self):
        from app.api.liminosity_routes import detect_signal, SignalRequest
        from app.config import settings
        settings.anthropic_api_key = "sk-ant-test"
        try:
            with patch("anthropic.Anthropic") as MockCls:
                client = MagicMock()
                MockCls.return_value = client
                client.messages.create.return_value = self._mock_resp()
                req = SignalRequest(input="Negotiation context", layer_index=1)
                result = detect_signal(req, _user=None)
                assert result["layer"] == "edge"
                signals = result["signals"]
                assert "perpendicular_question" in signals
                assert "negative_space" in signals
                assert "hidden_axis" in signals
                assert "operative_signal" in signals
                assert "signature_read" in signals
        finally:
            settings.anthropic_api_key = ""

    def test_signal_handles_fenced_json(self):
        from app.api.liminosity_routes import detect_signal, SignalRequest
        from app.config import settings
        settings.anthropic_api_key = "sk-ant-test"
        fenced = f"```json\n{self.VALID_SIGNAL_JSON}\n```"
        try:
            with patch("anthropic.Anthropic") as MockCls:
                client = MagicMock()
                MockCls.return_value = client
                resp = MagicMock()
                resp.content = [MagicMock(text=fenced)]
                client.messages.create.return_value = resp
                req = SignalRequest(input="input", layer_index=0)
                result = detect_signal(req, _user=None)
                assert result["signals"]["hidden_axis"] == "Optimizing for optics, not outcomes."
        finally:
            settings.anthropic_api_key = ""

    def test_signal_handles_malformed_json_gracefully(self):
        from app.api.liminosity_routes import detect_signal, SignalRequest
        from app.config import settings
        settings.anthropic_api_key = "sk-ant-test"
        try:
            with patch("anthropic.Anthropic") as MockCls:
                client = MagicMock()
                MockCls.return_value = client
                resp = MagicMock()
                resp.content = [MagicMock(text="not valid json at all")]
                client.messages.create.return_value = resp
                req = SignalRequest(input="input", layer_index=0)
                result = detect_signal(req, _user=None)
                assert "signature_read" in result["signals"]
                assert "shadow" in result["signals"]["signature_read"]
        finally:
            settings.anthropic_api_key = ""
