"""
Document extraction pipeline.
Accepts PDF / DOCX / plain-text and extracts dependency, obligation,
approval-chain, and assumption relationships as Graph nodes and edges.

NLP strategy: regex + keyword heuristics only — no model download required.
spaCy is used for sentence segmentation only if available.
"""
from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from app.models.graph import (
    Graph, Node, Edge,
    NodeType, EdgeType,
    NodeAttributes, EdgeAttributes,
)


# ---------------------------------------------------------------------------
# Text reading
# ---------------------------------------------------------------------------

def read_pdf(data: bytes) -> str:
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                # Try table extraction first
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            text_parts.append(" | ".join(str(c or "") for c in row))
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    except Exception as e:
        raise ValueError(f"PDF extraction failed: {e}") from e


def read_docx(data: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        raise ValueError(f"DOCX extraction failed: {e}") from e


def read_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def read_document(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return read_pdf(data)
    if ext in (".docx", ".doc"):
        return read_docx(data)
    return read_text(data)


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
        nlp.add_pipe("sentencizer")
        doc = nlp(text[:100_000])  # cap for performance
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    except Exception:
        # Fallback: split on sentence-ending punctuation
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ---------------------------------------------------------------------------
# Entity heuristics
# ---------------------------------------------------------------------------

# Capitalised multi-word phrases (2-4 words) that look like proper nouns
_ENTITY_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
)

_STOP_WORDS = {
    "The", "This", "That", "These", "Those", "Such", "All", "Any",
    "Each", "Both", "Either", "Neither", "Under", "Upon", "With",
    "For", "From", "Into", "After", "Before", "During", "Between",
}

_VENDOR_CLUES = {"Inc", "Ltd", "LLC", "Corp", "GmbH", "Co", "Group", "Holdings"}
_TEAM_CLUES = {"Team", "Department", "Dept", "Division", "Committee", "Board", "Council"}
_SYSTEM_CLUES = {"System", "Platform", "Software", "Application", "Service", "Tool", "Database"}
_PERSON_TITLES = {"CEO", "COO", "CFO", "CTO", "VP", "Director", "Manager", "Officer", "Head"}


def _classify_entity(phrase: str) -> NodeType:
    words = set(phrase.split())
    if words & _VENDOR_CLUES:
        return NodeType.VENDOR
    if words & _TEAM_CLUES:
        return NodeType.TEAM
    if words & _SYSTEM_CLUES:
        return NodeType.SYSTEM
    if words & _PERSON_TITLES:
        return NodeType.PERSON
    return NodeType.FUNCTION


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _similar_enough(a: str, b: str, threshold: float = 0.82) -> bool:
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio() >= threshold


def _resolve_entity(name: str, existing: dict[str, str]) -> str:
    """Return existing node ID if a similar entity already exists, else create new."""
    for eid, elabel in existing.items():
        if _similar_enough(name, elabel):
            return eid
    new_id = "doc_" + re.sub(r"\W+", "_", _normalise(name))[:40]
    existing[new_id] = name
    return new_id


# ---------------------------------------------------------------------------
# Relation patterns
# ---------------------------------------------------------------------------

@dataclass
class _Relation:
    subject: str
    relation: str
    obj: str
    sentence: str
    confidence: float = 0.6


_PATTERNS: list[tuple[re.Pattern, EdgeType, float]] = [
    # Dependency
    (re.compile(r"(?P<s>.+?)\s+depends?\s+on\s+(?P<o>.+)", re.I), EdgeType.DEPENDS_ON, 0.8),
    (re.compile(r"(?P<s>.+?)\s+requires?\s+(?P<o>.+)", re.I), EdgeType.DEPENDS_ON, 0.75),
    (re.compile(r"(?P<s>.+?)\s+is\s+contingent\s+on\s+(?P<o>.+)", re.I), EdgeType.CONTINGENT_ON, 0.8),
    (re.compile(r"without\s+(?P<o>.+?),\s+(?P<s>.+?)\s+cannot", re.I), EdgeType.DEPENDS_ON, 0.75),
    (re.compile(r"(?P<s>.+?)\s+cannot\s+proceed\s+without\s+(?P<o>.+)", re.I), EdgeType.DEPENDS_ON, 0.75),
    # Approval / governance
    (re.compile(r"(?P<s>.+?)\s+must\s+be\s+approved\s+by\s+(?P<o>.+)", re.I), EdgeType.APPROVES, 0.85),
    (re.compile(r"(?P<o>.+?)\s+approves?\s+(?P<s>.+)", re.I), EdgeType.APPROVES, 0.8),
    (re.compile(r"(?P<s>.+?)\s+is\s+governed\s+by\s+(?P<o>.+)", re.I), EdgeType.GOVERNED_BY, 0.8),
    (re.compile(r"(?P<o>.+?)\s+signs?\s+off\s+on\s+(?P<s>.+)", re.I), EdgeType.APPROVES, 0.8),
    (re.compile(r"(?P<s>.+?)\s+requires?\s+sign.?off\s+from\s+(?P<o>.+)", re.I), EdgeType.APPROVES, 0.8),
    (re.compile(r"(?P<s>.+?)\s+escalates?\s+to\s+(?P<o>.+)", re.I), EdgeType.ESCALATES_TO, 0.8),
    # Obligation / timing
    (re.compile(r"(?P<s>.+?)\s+shall\s+(?:notify|inform|update|report\s+to)\s+(?P<o>.+)", re.I), EdgeType.INFORMS, 0.75),
    (re.compile(r"(?P<s>.+?)\s+must\s+(?:notify|inform|update|report\s+to)\s+(?P<o>.+)", re.I), EdgeType.INFORMS, 0.75),
    (re.compile(r"(?P<s>.+?)\s+before\s+(?P<o>.+?)\s+can\s+proceed", re.I), EdgeType.TIMED_BEFORE, 0.7),
    (re.compile(r"(?P<s>.+?)\s+funds?\s+(?P<o>.+)", re.I), EdgeType.FUNDS, 0.75),
    (re.compile(r"(?P<s>.+?)\s+finances?\s+(?P<o>.+)", re.I), EdgeType.FUNDS, 0.75),
    (re.compile(r"(?P<o>.+?)\s+is\s+funded\s+by\s+(?P<s>.+)", re.I), EdgeType.FUNDS, 0.75),
    (re.compile(r"(?P<s>.+?)\s+blocks?\s+(?P<o>.+)", re.I), EdgeType.BLOCKS, 0.7),
    (re.compile(r"(?P<s>.+?)\s+substitutes?\s+(?:for\s+)?(?P<o>.+)", re.I), EdgeType.SUBSTITUTES, 0.7),
]

_ASSUMPTION_PATTERNS = [
    re.compile(r"\b(assumes?|assuming|subject\s+to|provided\s+that|on\s+the\s+assumption\s+that|predicated\s+on)\b", re.I),
    re.compile(r"\b(it\s+is\s+expected\s+that|expected\s+to\s+remain|this\s+will\s+not|under\s+current\s+conditions|barring\s+unforeseen|assuming\s+normal)\b", re.I),
    re.compile(r"\b(should\s+be\s+available|is\s+expected\s+to\s+deliver|will\s+presumably)\b", re.I),
]


def _extract_entities(text: str) -> list[str]:
    matches = _ENTITY_PATTERN.findall(text)
    return [m for m in matches if m not in _STOP_WORDS]


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

@dataclass
class DocumentExtractionResult:
    nodes: list[Node]
    edges: list[Edge]
    assumption_sentences: list[str]
    entity_count: int
    relation_count: int
    confidence_notes: list[str]


class TextRelationExtractor:
    """
    Extracts dependency/approval/obligation/assumption relations from text.
    Returns a DocumentExtractionResult suitable for merging into a Graph.
    """

    def __init__(self, source_name: str = "document"):
        self.source_name = source_name

    def extract(self, text: str) -> DocumentExtractionResult:
        sentences = split_sentences(text)
        entity_registry: dict[str, str] = {}  # id → label
        relations: list[tuple[str, EdgeType, str, float, str]] = []  # src, etype, tgt, conf, sent
        assumption_sents: list[str] = []

        # Count entity frequency across all sentences
        entity_freq: dict[str, int] = {}
        for sent in sentences:
            for ent in _extract_entities(sent):
                entity_freq[ent] = entity_freq.get(ent, 0) + 1

        # Only retain entities mentioned ≥2 times
        frequent_entities = {e for e, c in entity_freq.items() if c >= 2}

        for sent in sentences:
            sent_clean = sent.strip()

            # Assumption detection
            if any(p.search(sent_clean) for p in _ASSUMPTION_PATTERNS):
                assumption_sents.append(sent_clean)

            # Relation extraction
            for pattern, edge_type, conf in _PATTERNS:
                m = pattern.search(sent_clean)
                if not m:
                    continue
                try:
                    subj_raw = m.group("s").strip()
                    obj_raw = m.group("o").strip()
                except IndexError:
                    continue

                # Strip trailing punctuation and subordinate clauses
                subj_raw = re.sub(r"[,;.]\s*.*$", "", subj_raw).strip()
                obj_raw = re.sub(r"[,;.]\s*.*$", "", obj_raw).strip()

                if not subj_raw or not obj_raw or subj_raw == obj_raw:
                    continue
                if len(subj_raw) > 80 or len(obj_raw) > 80:
                    continue

                sid = _resolve_entity(subj_raw, entity_registry)
                oid = _resolve_entity(obj_raw, entity_registry)

                # Boost confidence if entities appear frequently
                boost = 0.1 if (subj_raw in frequent_entities or obj_raw in frequent_entities) else 0.0
                relations.append((sid, edge_type, oid, min(1.0, conf + boost), sent_clean))

        # Build nodes
        nodes: list[Node] = []
        for eid, elabel in entity_registry.items():
            freq = entity_freq.get(elabel, 1)
            confidence = min(0.9, 0.6 + (freq - 1) * 0.05)
            nodes.append(Node(
                id=eid,
                label=elabel,
                node_type=_classify_entity(elabel),
                attributes=NodeAttributes(
                    confidence=confidence,
                    evidence_source=self.source_name,
                ),
            ))

        # Build assumption nodes
        for i, asent in enumerate(assumption_sents[:20]):  # cap at 20
            aid = f"assumption_{uuid.uuid4().hex[:8]}"
            # Extract the core claim (first 60 chars)
            claim = re.sub(r"\s+", " ", asent[:60]).strip()
            nodes.append(Node(
                id=aid,
                label=f"Assumption: {claim}…" if len(asent) > 60 else f"Assumption: {asent}",
                node_type=NodeType.ASSUMPTION,
                attributes=NodeAttributes(
                    confidence=0.5,
                    replaceability=0.0,
                    evidence_source=self.source_name,
                ),
            ))

        # Build edges (deduplicate same src+type+tgt)
        seen_edges: set[tuple] = set()
        edges: list[Edge] = []
        for src, etype, tgt, conf, sent in relations:
            key = (src, etype.value, tgt)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(Edge(
                id=f"doc_{uuid.uuid4().hex[:8]}",
                source=src,
                target=tgt,
                edge_type=etype,
                attributes=EdgeAttributes(reliability=conf),
            ))

        notes = []
        if len(nodes) == 0:
            notes.append("No entities found — document may not contain named relationships.")
        if len(assumption_sents) > 10:
            notes.append(f"{len(assumption_sents)} assumption sentences detected — document has high implicit dependency load.")

        return DocumentExtractionResult(
            nodes=nodes,
            edges=edges,
            assumption_sentences=assumption_sents,
            entity_count=len(entity_registry),
            relation_count=len(edges),
            confidence_notes=notes,
        )


def extract_from_document(filename: str, data: bytes) -> DocumentExtractionResult:
    text = read_document(filename, data)
    extractor = TextRelationExtractor(source_name=filename)
    return extractor.extract(text)


def merge_into_graph(graph: Graph, result: DocumentExtractionResult) -> Graph:
    """Add extracted nodes/edges into an existing graph (in-place)."""
    existing_ids = {n.id for n in graph.nodes}
    for node in result.nodes:
        if node.id not in existing_ids:
            graph.nodes.append(node)
            existing_ids.add(node.id)

    existing_edge_keys = {(e.source, e.edge_type, e.target) for e in graph.edges}
    for edge in result.edges:
        key = (edge.source, edge.edge_type, edge.target)
        if key not in existing_edge_keys and edge.source in existing_ids and edge.target in existing_ids:
            graph.edges.append(edge)
            existing_edge_keys.add(key)

    return graph
