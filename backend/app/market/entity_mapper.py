"""
Entity mapper — resolves graph node labels to real-world identifiers
(stock tickers, SEC CIK numbers) for market data enrichment.

Priority order:
  1. Explicit metadata on the node: node.attributes.metadata["ticker"] or ["cik"]
  2. User-supplied mapping table passed directly
  3. Search name fallback to node label

The mapper never makes network calls — only resolves identifiers.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.graph import Node


class EntityRef:
    __slots__ = ("node_id", "node_label", "ticker", "cik", "search_name")

    def __init__(
        self,
        node_id: str,
        node_label: str,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        search_name: Optional[str] = None,
    ):
        self.node_id = node_id
        self.node_label = node_label
        self.ticker = ticker
        self.cik = cik
        self.search_name = search_name or node_label

    def has_market_data(self) -> bool:
        return bool(self.ticker or self.cik)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "node_label": self.node_label,
            "ticker": self.ticker,
            "cik": self.cik,
            "search_name": self.search_name,
            "has_market_data": self.has_market_data(),
        }


def resolve_entities(
    nodes: list[Node],
    user_mappings: dict[str, dict] | None = None,
) -> list[EntityRef]:
    """
    Resolve a list of nodes to EntityRef objects.
    user_mappings: {node_id: {"ticker": "AAPL", "cik": "0000320193", "search_name": "Apple Inc"}}
    """
    mappings = user_mappings or {}
    refs: list[EntityRef] = []

    for node in nodes:
        meta = node.attributes.metadata or {}
        um = mappings.get(node.id, {})

        refs.append(EntityRef(
            node_id=node.id,
            node_label=node.label,
            ticker=meta.get("ticker") or um.get("ticker"),
            cik=meta.get("cik") or um.get("cik"),
            search_name=meta.get("search_name") or um.get("search_name") or node.label,
        ))

    return refs
