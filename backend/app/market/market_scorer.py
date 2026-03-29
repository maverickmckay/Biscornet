"""
Market-enhanced reversion scorer.

Takes a GraphAnalysis and a set of market signals and produces:
  - Enhanced reversion_potential_score per collapse point
  - MarketIntelligence objects that explain the reversion map
  - Named reversion beneficiaries with market context

This module is called AFTER the core analysis. It adds a market layer
on top of the structural analysis — it does not replace it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.models.graph import Graph, GraphAnalysis, CollapsePoint
from app.market.entity_mapper import EntityRef, resolve_entities
from app.market.adapters import (
    SECSignal, NewsSignal, PriceSignal,
    fetch_sec_entity, fetch_news, fetch_price,
)


@dataclass
class ReversionBeneficiary:
    node_id: str
    node_label: str
    mechanism: str           # "substitute", "escalation_target", "market_gainer"
    market_evidence: list[str]
    strength: float          # 0-1


@dataclass
class MarketIntelligence:
    node_id: str
    node_label: str
    sec_signal: Optional[SECSignal]
    news_signal: Optional[NewsSignal]
    price_signal: Optional[PriceSignal]
    market_risk_delta: float          # additive to nnm_score (-0.2 to +0.2)
    reversion_beneficiaries: list[ReversionBeneficiary]
    narrative: str


async def _fetch_signals_for_ref(
    ref: EntityRef,
    client: httpx.AsyncClient,
) -> tuple[Optional[SECSignal], Optional[NewsSignal], Optional[PriceSignal]]:
    """Fetch all signals for one entity concurrently."""
    tasks = []

    if ref.cik:
        tasks.append(fetch_sec_entity(ref.cik, client))
    else:
        tasks.append(asyncio.sleep(0, result=None))

    tasks.append(fetch_news(ref.search_name, client))

    if ref.ticker:
        tasks.append(fetch_price(ref.ticker, client))
    else:
        tasks.append(asyncio.sleep(0, result=None))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return (
        results[0] if not isinstance(results[0], Exception) else None,
        results[1] if not isinstance(results[1], Exception) else None,
        results[2] if not isinstance(results[2], Exception) else None,
    )


def _compute_risk_delta(
    sec: Optional[SECSignal],
    news: Optional[NewsSignal],
    price: Optional[PriceSignal],
) -> float:
    """
    Additive adjustment to NNM score based on market signals.
    Range: -0.2 (market signals healthy) to +0.2 (signals show stress).
    """
    delta = 0.0

    if sec:
        if sec.risk_level == "high":
            delta += 0.12
        elif sec.risk_level == "medium":
            delta += 0.06

    if news:
        # Negative sentiment → more risk
        delta -= news.sentiment_score * 0.08  # negative score adds positive delta

    if price:
        if price.trend == "down" and price.price_change_30d is not None:
            # >10% drop → meaningful stress signal
            delta += min(0.10, abs(price.price_change_30d) / 100 * 0.5)
        elif price.trend == "up":
            delta -= 0.04  # positive trend is mild protective signal

    return round(max(-0.20, min(0.20, delta)), 4)


def _build_narrative(
    label: str,
    sec: Optional[SECSignal],
    news: Optional[NewsSignal],
    price: Optional[PriceSignal],
    delta: float,
) -> str:
    parts = [f"Market intelligence for '{label}':"]

    if sec and sec.material_event_count > 0:
        parts.append(f"{sec.material_event_count} material SEC filing(s) in the past year (latest: {sec.latest_form} on {sec.latest_date}).")
    elif sec:
        parts.append("No recent material SEC events.")

    if news and news.article_count > 0:
        sentiment = "negative" if news.sentiment_score < -0.1 else "positive" if news.sentiment_score > 0.1 else "neutral"
        parts.append(f"{news.article_count} recent mentions in public filings ({sentiment} tone).")

    if price and price.price_change_30d is not None:
        parts.append(f"30-day price change: {price.price_change_30d:+.1f}% (trend: {price.trend}).")

    if delta > 0.05:
        parts.append(f"Market signals increase structural risk estimate by {delta:.0%}.")
    elif delta < -0.05:
        parts.append(f"Market signals suggest lower near-term stress ({delta:.0%} adjustment).")

    return " ".join(parts) if len(parts) > 1 else "No market data available for this entity."


async def enrich_analysis(
    graph: Graph,
    analysis: GraphAnalysis,
    user_mappings: dict[str, dict] | None = None,
    max_entities: int = 20,
) -> tuple[GraphAnalysis, list[MarketIntelligence]]:
    """
    Enrich a GraphAnalysis with market signals.
    Returns the (modified) analysis and a list of MarketIntelligence objects.

    Modifies collapse_point.reversion_potential_score in-place.
    Does NOT modify nnm_score directly — that stays structural.
    """
    # Only enrich collapse points (the most important nodes)
    cp_ids = {cp.node_id for cp in analysis.collapse_points[:max_entities]}
    nodes_to_enrich = [n for n in graph.nodes if n.id in cp_ids]

    refs = resolve_entities(nodes_to_enrich, user_mappings)

    async with httpx.AsyncClient(
        timeout=12.0,
        headers={"User-Agent": "NoNextMove/0.3 research@example.com"},
    ) as client:
        signal_tasks = [_fetch_signals_for_ref(ref, client) for ref in refs]
        all_signals = await asyncio.gather(*signal_tasks, return_exceptions=True)

    intel_list: list[MarketIntelligence] = []
    signal_map: dict[str, tuple] = {}

    for ref, signals in zip(refs, all_signals):
        if isinstance(signals, Exception):
            signals = (None, None, None)
        sec, news, price = signals
        delta = _compute_risk_delta(sec, news, price)
        narrative = _build_narrative(ref.node_label, sec, news, price, delta)
        signal_map[ref.node_id] = (sec, news, price, delta, narrative)

        intel = MarketIntelligence(
            node_id=ref.node_id,
            node_label=ref.node_label,
            sec_signal=sec,
            news_signal=news,
            price_signal=price,
            market_risk_delta=delta,
            reversion_beneficiaries=[],
            narrative=narrative,
        )
        intel_list.append(intel)

    # Patch reversion_potential_score on collapse points
    for cp in analysis.collapse_points:
        if cp.node_id in signal_map:
            _, _, price, delta, _ = signal_map[cp.node_id]
            # Reversion potential rises when structural score is high and
            # market shows stress (others will benefit)
            market_boost = max(0.0, delta) * 0.5
            cp.reversion_potential_score = round(
                min(1.0, cp.reversion_potential_score + market_boost), 4
            )

    return analysis, intel_list
