"""Market intelligence API endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.crud import get_graph, get_latest_analysis
from app.engines.analyzer import analyze
from app.market.market_scorer import enrich_analysis, MarketIntelligence
from app.auth.auth import get_optional_user

router = APIRouter(prefix="/market", tags=["market"])


class EnrichRequest(BaseModel):
    user_mappings: Optional[dict[str, dict]] = None   # node_id → {ticker, cik}
    max_entities: int = 20


def _intel_to_dict(intel: MarketIntelligence) -> dict:
    return {
        "node_id": intel.node_id,
        "node_label": intel.node_label,
        "market_risk_delta": intel.market_risk_delta,
        "narrative": intel.narrative,
        "sec_signal": {
            "company_name": intel.sec_signal.company_name,
            "cik": intel.sec_signal.cik,
            "risk_level": intel.sec_signal.risk_level,
            "material_event_count": intel.sec_signal.material_event_count,
            "latest_form": intel.sec_signal.latest_form,
            "latest_date": intel.sec_signal.latest_date,
        } if intel.sec_signal else None,
        "news_signal": {
            "query": intel.news_signal.query,
            "article_count": intel.news_signal.article_count,
            "sentiment_score": intel.news_signal.sentiment_score,
            "top_headlines": intel.news_signal.top_headlines,
        } if intel.news_signal else None,
        "price_signal": {
            "ticker": intel.price_signal.ticker,
            "price": intel.price_signal.price,
            "price_change_30d": intel.price_signal.price_change_30d,
            "trend": intel.price_signal.trend,
        } if intel.price_signal else None,
    }


@router.post("/graphs/{graph_id}/enrich")
async def enrich_graph_analysis(
    graph_id: str,
    req: EnrichRequest,
    db: Session = Depends(get_db),
    _user=Depends(get_optional_user),
):
    """
    Enrich the stored analysis for a graph with real market signals.

    - Fetches SEC EDGAR filings, EDGAR full-text news, and Yahoo Finance prices
    - Patches reversion_potential_score on collapse points
    - Returns market intelligence per node
    """
    graph_rec = get_graph(db, graph_id)
    if not graph_rec:
        raise HTTPException(status_code=404, detail="Graph not found")

    from app.models.graph import Graph as GraphModel
    graph = GraphModel.model_validate_json(graph_rec.graph_json)

    # Use cached analysis or re-run
    analysis_rec = get_latest_analysis(db, graph_id)
    if analysis_rec:
        from app.models.graph import GraphAnalysis
        analysis = GraphAnalysis.model_validate_json(analysis_rec.analysis_json)
    else:
        analysis = analyze(graph)

    try:
        enriched_analysis, intel_list = await enrich_analysis(
            graph,
            analysis,
            user_mappings=req.user_mappings,
            max_entities=req.max_entities,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data fetch failed: {exc}")

    return {
        "graph_id": graph_id,
        "market_intelligence": [_intel_to_dict(i) for i in intel_list],
        "enriched_collapse_points": [
            {
                "node_id": cp.node_id,
                "node_label": cp.node_label,
                "nnm_score": cp.nnm_score,
                "reversion_potential_score": cp.reversion_potential_score,
            }
            for cp in enriched_analysis.collapse_points
        ],
    }
