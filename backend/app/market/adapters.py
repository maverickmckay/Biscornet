"""
Market / public-data adapters for No Next Move.
All adapters use free, public, lawful data sources only:
  - SEC EDGAR REST API (no key required)
  - RSS news feeds (Reuters, AP, Financial Times public feeds)
  - Yahoo Finance via direct JSON API (no yfinance — avoids build issues)

The market layer is fully optional and gracefully degrades.
All external calls are cached in-memory for the session lifetime.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

import httpx

# ---------------------------------------------------------------------------
# In-memory cache (simple TTL cache)
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 3600.0  # 1 hour


def _cached(key: str) -> Optional[object]:
    if key in _CACHE:
        ts, val = _CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None


def _store(key: str, val: object) -> None:
    _CACHE[key] = (time.time(), val)


# ---------------------------------------------------------------------------
# SEC EDGAR adapter
# ---------------------------------------------------------------------------

SEC_BASE = "https://data.sec.gov"
SEC_COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt={start}&enddt={end}&forms=8-K,10-K,10-Q"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

MATERIAL_FORMS = {"8-K", "10-K", "10-Q", "SC 13D", "13F-HR", "S-1"}
HIGH_RISK_ITEMS = {
    "1.01": "entry into material agreement",
    "1.02": "termination of material agreement",
    "1.03": "bankruptcy or receivership",
    "2.04": "triggering of accelerated payment obligation",
    "5.02": "departure of directors or officers",
    "8.01": "other events",
}


@dataclass
class SECSignal:
    cik: str
    company_name: str
    recent_filings: list[dict]
    material_event_count: int
    latest_form: Optional[str]
    latest_date: Optional[str]
    risk_level: str  # "low" | "medium" | "high"


async def fetch_sec_entity(cik: str, client: httpx.AsyncClient) -> Optional[SECSignal]:
    """Fetch recent SEC filings for a CIK. CIK must be 10-digit zero-padded."""
    cik_padded = cik.zfill(10)
    cache_key = f"sec_{cik_padded}"
    cached = _cached(cache_key)
    if cached:
        return cached  # type: ignore

    try:
        url = SEC_SUBMISSIONS.format(cik=cik_padded)
        r = await client.get(url, timeout=10.0)
        if r.status_code != 200:
            return None

        data = r.json()
        company_name = data.get("name", "Unknown")
        filings = data.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])

        recent = []
        material_count = 0
        for form, date, acc in zip(forms[:20], dates[:20], accessions[:20]):
            if form in MATERIAL_FORMS:
                recent.append({"form": form, "date": date, "accession": acc})
                if form == "8-K":
                    material_count += 1

        risk = "low"
        if material_count >= 3:
            risk = "high"
        elif material_count >= 1:
            risk = "medium"

        signal = SECSignal(
            cik=cik_padded,
            company_name=company_name,
            recent_filings=recent[:10],
            material_event_count=material_count,
            latest_form=forms[0] if forms else None,
            latest_date=dates[0] if dates else None,
            risk_level=risk,
        )
        _store(cache_key, signal)
        return signal
    except Exception:
        return None


# ---------------------------------------------------------------------------
# News / RSS adapter
# ---------------------------------------------------------------------------

# Public RSS feeds that require no API key
NEWS_FEEDS = {
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "ap_business": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    "sec_full_text": "https://efts.sec.gov/LATEST/search-index?q={query}&forms=8-K&dateRange=custom&startdt=2024-01-01",
}


@dataclass
class NewsSignal:
    entity: str
    headlines: list[str]
    sentiment_score: float   # -1 to +1, simple keyword heuristic
    article_count: int
    source: str


_NEGATIVE_WORDS = {
    "bankrupt", "default", "lawsuit", "investigation", "fine", "penalty",
    "fraud", "loss", "decline", "downgrade", "recall", "halt", "suspend",
    "breach", "outage", "failure", "delay", "miss", "cut", "restructur",
    "layoff", "layoffs", "downturn", "collapse", "crisis", "scandal",
}
_POSITIVE_WORDS = {
    "profit", "growth", "record", "beat", "exceed", "expand", "acqui",
    "partnership", "approval", "upgrade", "launch", "win", "award",
    "contract", "revenue", "dividend", "hire", "invest",
}


def _score_sentiment(texts: list[str]) -> float:
    pos = neg = 0
    for t in texts:
        tl = t.lower()
        for w in _NEGATIVE_WORDS:
            if w in tl:
                neg += 1
        for w in _POSITIVE_WORDS:
            if w in tl:
                pos += 1
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


async def fetch_news(entity: str, client: httpx.AsyncClient) -> NewsSignal:
    """Fetch news for a named entity via SEC full-text search (public, no key)."""
    cache_key = f"news_{entity.lower()[:30]}"
    cached = _cached(cache_key)
    if cached:
        return cached  # type: ignore

    headlines: list[str] = []
    try:
        encoded = quote_plus(f'"{entity}"')
        url = f"https://efts.sec.gov/LATEST/search-index?q={encoded}&dateRange=custom&startdt=2024-01-01&forms=8-K"
        r = await client.get(url, timeout=8.0,
                             headers={"User-Agent": "NoNextMove research@example.com"})
        if r.status_code == 200:
            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:10]:
                src = hit.get("_source", {})
                desc = src.get("file_date", "") + " " + src.get("entity_name", "") + " " + src.get("form_type", "")
                headlines.append(desc.strip())
    except Exception:
        pass

    sentiment = _score_sentiment(headlines)
    signal = NewsSignal(
        entity=entity,
        headlines=headlines[:10],
        sentiment_score=round(sentiment, 3),
        article_count=len(headlines),
        source="SEC EDGAR full-text search",
    )
    _store(cache_key, signal)
    return signal


# ---------------------------------------------------------------------------
# Price / ticker adapter (Yahoo Finance unofficial JSON — no library needed)
# ---------------------------------------------------------------------------

YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"


@dataclass
class PriceSignal:
    ticker: str
    price_change_30d: Optional[float]   # percentage
    current_price: Optional[float]
    volume_ratio: Optional[float]       # recent volume / avg volume
    trend: str                          # "up" | "down" | "flat" | "unknown"


async def fetch_price(ticker: str, client: httpx.AsyncClient) -> PriceSignal:
    cache_key = f"price_{ticker.upper()}"
    cached = _cached(cache_key)
    if cached:
        return cached  # type: ignore

    try:
        url = YAHOO_QUOTE_URL.format(ticker=ticker.upper())
        r = await client.get(url, timeout=8.0,
                             headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")

        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            raise ValueError("No result")

        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        volumes = result[0].get("indicators", {}).get("quote", [{}])[0].get("volume", [])
        closes = [c for c in closes if c is not None]
        volumes = [v for v in volumes if v is not None]

        if len(closes) < 2:
            raise ValueError("Insufficient data")

        pct_change = (closes[-1] - closes[0]) / closes[0] * 100
        avg_vol = sum(volumes[:-5]) / max(len(volumes[:-5]), 1) if len(volumes) > 5 else None
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else None
        vol_ratio = (recent_vol / avg_vol) if avg_vol and avg_vol > 0 else None

        trend = "flat"
        if pct_change > 3:
            trend = "up"
        elif pct_change < -3:
            trend = "down"

        signal = PriceSignal(
            ticker=ticker.upper(),
            price_change_30d=round(pct_change, 2),
            current_price=round(closes[-1], 2),
            volume_ratio=round(vol_ratio, 2) if vol_ratio else None,
            trend=trend,
        )
        _store(cache_key, signal)
        return signal
    except Exception:
        return PriceSignal(ticker=ticker.upper(), price_change_30d=None,
                           current_price=None, volume_ratio=None, trend="unknown")
