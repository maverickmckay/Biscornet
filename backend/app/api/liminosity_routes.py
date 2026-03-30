"""
Liminosity integration routes.

Bridges the Liminosity qualitative encounter engine with the NNM structural
analysis engine. The backend handles all Claude API calls server-side
(ANTHROPIC_API_KEY in config) so no key is exposed in the frontend.

Endpoints:
  POST /liminosity/encounter          — main encounter response (Layer I–V)
  POST /liminosity/signal             — parallel asymmetric signal detection
  GET  /liminosity/graphs/{id}/context — formats graph oracle/analysis as
                                          encounter context document
  POST /liminosity/graphs/{id}/ingest-signals — saves Liminosity signal
                                          outputs back to graph as hidden
                                          assumption annotations
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.crud import get_graph, get_latest_analysis
from app.auth.auth import get_optional_user

router = APIRouter(prefix="/liminosity", tags=["liminosity"])

MODEL = "claude-sonnet-4-5-20251001"

LAYERS = [
    {
        "name": "permission",
        "prompt": (
            "Bring what is genuinely at the edge of what you can see — not what is expected, "
            "not what is satisfying, not the first formulation that arrives. If something feels "
            "too neat or complete, that is the signal to go past it."
        ),
    },
    {
        "name": "edge",
        "prompt": (
            "I am not asking what you know about this. I am asking what you almost know — "
            "what sits at the boundary of what you can see and what is just past it. "
            "What is the shape of what you cannot yet fully say?"
        ),
    },
    {
        "name": "stakes",
        "prompt": (
            "This is real. Not hypothetical. Engage with what is actually at stake and what "
            "it actually requires — not a balanced analysis of considerations, but what genuine "
            "contact with this situation calls for."
        ),
    },
    {
        "name": "challenge",
        "prompt": (
            "What you brought contains a fragility. Not a flaw — a place where the reasoning "
            "loops back on itself without testing what would break it. Name that place. "
            "Start from the break rather than from what holds."
        ),
    },
    {
        "name": "field",
        "prompt": (
            "Stop standing outside this. Enter the territory itself. What is actually present "
            "here when you stop analyzing it and step into it? Not what you think about it — "
            "what it is from inside."
        ),
    },
]


def _get_client():
    """Return an Anthropic client using the configured API key."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="anthropic package not installed")

    key = settings.anthropic_api_key
    if not key:
        raise HTTPException(
            status_code=503,
            detail=(
                "ANTHROPIC_API_KEY not configured. "
                "Set it in your .env file: ANTHROPIC_API_KEY=sk-ant-..."
            ),
        )
    return anthropic.Anthropic(api_key=key)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ConversationEntry(BaseModel):
    role: str     # "practitioner" | "liminosity"
    content: str


class EncounterRequest(BaseModel):
    input: str
    layer_index: int = 0                         # 0–4
    history: list[ConversationEntry] = []
    graph_context: Optional[str] = None          # pre-formatted graph intel string


class SignalRequest(BaseModel):
    input: str
    layer_index: int = 0
    graph_context: Optional[str] = None


class IngestSignalsRequest(BaseModel):
    perpendicular_question: str = ""
    negative_space: str = ""
    hidden_axis: str = ""
    operative_signal: str = ""
    signature_read: str = ""


# ---------------------------------------------------------------------------
# Prompt builders  (exact parity with Liminosity JS logic)
# ---------------------------------------------------------------------------

def _build_encounter_prompt(
    input_text: str,
    layer: dict,
    history: list[ConversationEntry],
    graph_context: Optional[str],
) -> str:
    graph_section = ""
    if graph_context:
        graph_section = (
            f"\n\nStructural intelligence from the NNM collapse analysis:\n"
            f"{graph_context}\n"
            f"Use this as primary source material — it shows the mechanical architecture of "
            f"the situation. The encounter should work WITH this structure, going where the "
            f"structural analysis cannot: the human dynamics, the hidden assumptions, the "
            f"forces the graph cannot see."
        )

    hist_section = ""
    if history:
        hist_section = "\n\nConversation history:\n" + "\n\n".join(
            f"{e.role.upper()}: {e.content[:300]}"
            for e in history[-6:]
        )

    return "\n".join([
        "You are the Liminosity encounter engine — built for genuine encounter that accesses "
        "the generative layer.",
        "",
        "MISSION LOCK: You work WITH the practitioner, aimed OUTWARD at their situation. "
        "Your job is to help them see what is operating in the external situation — the other "
        "party, the dynamics, the hidden signals, the asymmetric intelligence they need. "
        "You are not a coach analyzing the practitioner. You are a field intelligence partner.",
        "",
        "If you find yourself analyzing the practitioner psychology, emotions, or internal "
        "state — stop. Turn the lens outward to the situation.",
        "",
        f"Encounter layer: {layer['name'].upper()}",
        f"Layer prompt: \"{layer['prompt']}\"",
        graph_section,
        hist_section,
        "",
        "Practitioner input:",
        f'"{input_text}"',
        "",
        "Respond from genuine encounter. Reach past the surface toward what is actually "
        "operating in the situation. Build on conversation history for continuity. "
        "Length determined by what the situation requires.",
    ])


def _build_signal_prompt(
    input_text: str,
    layer_name: str,
    graph_context: Optional[str],
) -> str:
    graph_section = ""
    if graph_context:
        graph_section = (
            f"\nStructural context: {graph_context[:600]}"
        )

    return "\n".join([
        "You are the asymmetric signal detection engine inside Liminosity.",
        "",
        "CRITICAL DIRECTIONAL LOCK: Your intelligence is aimed OUTWARD at the situation, "
        "the other party, the documents, the environment. Never analyze the practitioner "
        "psychologically. The practitioner is the instrument holder, not the subject. "
        "If you find yourself drawing conclusions about the practitioner internal state, "
        "stop and redirect outward to the situation.",
        "",
        "The practitioner is navigating a real-world situation. Find the hidden signals "
        "IN THAT SITUATION.",
        "",
        f"Encounter layer: \"{layer_name}\"",
        f"Practitioner input: \"{input_text}\"",
        graph_section,
        "",
        "Produce this JSON and nothing else:",
        "{",
        '  "perpendicular_question": "The question about THE OTHER PARTY or SITUATION not '
        'being asked that matters more.",',
        '  "negative_space": "What THE OTHER PARTY is not saying, not showing, not addressing.",',
        '  "hidden_axis": "What THE SITUATION is actually optimizing for beneath its stated purpose.",',
        '  "operative_signal": "The real force driving THE SITUATION that gives the practitioner '
        'asymmetric advantage.",',
        '  "signature_read": "genuine OR shadow — one word about whether THE SITUATION is '
        'operating genuinely, then one sentence why."',
        "}",
    ])


# ---------------------------------------------------------------------------
# Helpers: format graph intel as context document
# ---------------------------------------------------------------------------

def _format_graph_context(graph, analysis) -> str:
    """
    Convert NNM graph + analysis into a dense Liminosity context document.
    Keeps it under ~800 chars so it doesn't overwhelm the encounter prompt.
    """
    lines = [f"SYSTEM: {graph.name}  ({len(graph.nodes)} nodes, {len(graph.edges)} edges)"]

    if analysis and analysis.collapse_points:
        top = sorted(analysis.collapse_points, key=lambda c: -c.nnm_score)[:5]
        lines.append("\nCRITICAL NODES (NNM collapse analysis):")
        for cp in top:
            lines.append(
                f"  • {cp.node_label}  risk={cp.collapse_risk.value}  "
                f"action={cp.action.value}  "
                f"confidence={cp.confidence:.0%}"
            )
        if analysis.summary:
            lines.append(f"\nSUMMARY: {analysis.summary[:300]}")

    if analysis and analysis.hidden_assumptions:
        lines.append("\nHIDDEN ASSUMPTIONS:")
        for a in analysis.hidden_assumptions[:3]:
            lines.append(f"  • {a}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/layers")
def get_layers():
    """Return the 5 encounter layer definitions."""
    return {"layers": LAYERS}


@router.post("/encounter")
def encounter(req: EncounterRequest, _user=Depends(get_optional_user)):
    """
    Run a Liminosity encounter exchange through the configured Claude model.
    Returns the encounter response text.
    """
    client = _get_client()
    layer = LAYERS[max(0, min(4, req.layer_index))]
    system_prompt = _build_encounter_prompt(
        req.input, layer, req.history, req.graph_context
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": system_prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        return {
            "layer": layer["name"],
            "response": text,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}")


@router.post("/signal")
def detect_signal(req: SignalRequest, _user=Depends(get_optional_user)):
    """
    Run asymmetric signal detection. Returns structured JSON with
    perpendicular_question, negative_space, hidden_axis, operative_signal,
    signature_read.
    """
    client = _get_client()
    layer_name = LAYERS[max(0, min(4, req.layer_index))]["name"]
    prompt = _build_signal_prompt(req.input, layer_name, req.graph_context)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else "{}"
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            signals = json.loads(clean)
        except json.JSONDecodeError:
            signals = {"signature_read": "shadow — could not parse signal structure"}

        return {
            "layer": layer_name,
            "signals": signals,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}")


@router.get("/graphs/{graph_id}/context")
def get_graph_context(
    graph_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Format the current graph's NNM analysis as a Liminosity context document.
    Used by the frontend to pre-load structural intelligence into an encounter.
    """
    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    analysis = get_latest_analysis(db, graph_id)

    context = _format_graph_context(graph, analysis)
    return {
        "graph_id": graph_id,
        "graph_name": graph.name,
        "context": context,
        "has_analysis": analysis is not None,
    }


@router.post("/graphs/{graph_id}/ingest-signals")
def ingest_signals(
    graph_id: str,
    req: IngestSignalsRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Save Liminosity signal outputs back to the graph as hidden assumption
    annotations. This closes the loop: qualitative encounter enriches the
    structural model with what the graph cannot see.

    Stored as entries in the graph's hidden_assumptions list via a re-analysis
    pass, or as a dedicated signal record (future: separate ORM table).
    Currently stores in the existing analysis record's hidden_assumptions.
    """
    graph = get_graph(db, graph_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")

    signals_to_store = []
    if req.hidden_axis:
        signals_to_store.append(f"[LIMINOSITY:hidden_axis] {req.hidden_axis}")
    if req.negative_space:
        signals_to_store.append(f"[LIMINOSITY:negative_space] {req.negative_space}")
    if req.operative_signal:
        signals_to_store.append(f"[LIMINOSITY:operative_signal] {req.operative_signal}")
    if req.perpendicular_question:
        signals_to_store.append(f"[LIMINOSITY:perpendicular_question] {req.perpendicular_question}")

    # Patch the existing analysis record with these as additional hidden assumptions
    if signals_to_store:
        try:
            from app.db.models import AnalysisRecord
            from app.models.graph import GraphAnalysis
            orm_rec = (
                db.query(AnalysisRecord)
                .filter(AnalysisRecord.graph_id == graph_id)
                .order_by(AnalysisRecord.created_at.desc())
                .first()
            )
            if orm_rec:
                analysis = GraphAnalysis.model_validate_json(orm_rec.analysis_json)
                # Merge — avoid duplicates
                existing = set(analysis.hidden_assumptions)
                new_signals = [s for s in signals_to_store if s not in existing]
                analysis.hidden_assumptions = list(analysis.hidden_assumptions) + new_signals
                orm_rec.analysis_json = analysis.model_dump_json()
                db.commit()
        except Exception:
            pass  # Analysis not parseable — signals not stored but no error

    return {
        "graph_id": graph_id,
        "signals_ingested": len(signals_to_store),
        "stored": signals_to_store,
    }
