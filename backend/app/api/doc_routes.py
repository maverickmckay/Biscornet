"""
Document extraction API routes.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db.database import get_db
from app.db.crud import save_graph, get_graph
from app.models.graph import Graph
from app.utils.doc_extract import extract_from_document, merge_into_graph

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}


@router.post("/documents/extract")
async def extract_document(
    file: UploadFile = File(...),
    graph_id: str = Form(None),
    db: Session = Depends(get_db),
):
    """
    Extract relationships from a PDF/DOCX/TXT document.
    If graph_id is provided, merge extracted nodes/edges into that graph.
    Returns the extracted sub-graph and extraction summary.
    """
    from pathlib import Path
    ext = Path(file.filename or "file.txt").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    data = await file.read()
    result = extract_from_document(file.filename or "document", data)

    if graph_id:
        graph = get_graph(db, graph_id)
        if not graph:
            raise HTTPException(404, f"Graph {graph_id} not found")
        graph = merge_into_graph(graph, result)
        save_graph(db, graph)
        target_graph_id = graph_id
    else:
        # Create a new graph from the extracted content
        new_graph = Graph(
            id=str(uuid.uuid4()),
            name=f"Extracted: {file.filename}",
            nodes=result.nodes,
            edges=result.edges,
        )
        save_graph(db, new_graph)
        target_graph_id = new_graph.id

    return {
        "graph_id": target_graph_id,
        "entity_count": result.entity_count,
        "relation_count": result.relation_count,
        "assumption_sentences": result.assumption_sentences[:10],
        "confidence_notes": result.confidence_notes,
        "nodes_added": len(result.nodes),
        "edges_added": len(result.edges),
    }


@router.post("/documents/extract-and-analyze")
async def extract_and_analyze(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Extract from document, save as new graph, and run immediate analysis."""
    from pathlib import Path
    from app.engines.analyzer import analyze
    from app.db.crud import save_analysis

    ext = Path(file.filename or "file.txt").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    data = await file.read()
    result = extract_from_document(file.filename or "document", data)

    graph = Graph(
        id=str(uuid.uuid4()),
        name=f"Extracted: {file.filename}",
        nodes=result.nodes,
        edges=result.edges,
    )

    if len(graph.nodes) < 2:
        return {
            "error": "Too few entities extracted to analyse. Document may lack relational language.",
            "extraction_summary": {
                "entity_count": result.entity_count,
                "confidence_notes": result.confidence_notes,
            },
        }

    save_graph(db, graph)
    analysis = analyze(graph)
    save_analysis(db, analysis)

    return {
        "graph_id": graph.id,
        "extraction_summary": {
            "entity_count": result.entity_count,
            "relation_count": result.relation_count,
            "assumption_sentences_count": len(result.assumption_sentences),
            "confidence_notes": result.confidence_notes,
        },
        "analysis": analysis.model_dump(),
    }
