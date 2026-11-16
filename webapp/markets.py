"""Read-only market data for the manual trading page (Gamma & CLOB APIs)."""

from __future__ import annotations

import json
import re
from typing import Any

import requests

import config

_session = requests.Session()
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,200}$")


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    response = _session.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def _loads(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value if value is not None else default


def normalise_slug(text: str) -> str:
    """Accept a slug or a full ``polymarket.com/event/<slug>`` URL."""
    text = (text or "").strip()
    match = re.search(r"polymarket\.com/(?:[a-z]{2}/)?event/([^/?#]+)", text)
    slug = (match.group(1) if match else text).strip("/").lower()
    if not _SLUG_RE.match(slug):
        raise ValueError("slug の形式が正しくありません")
    return slug


def market_json(market: dict[str, Any]) -> dict[str, Any]:
    names = _loads(market.get("outcomes"), [])
    prices = _loads(market.get("outcomePrices"), [])
    token_ids = _loads(market.get("clobTokenIds"), [])
    outcomes = [
        {"name": name, "price": float(price) if price not in (None, "") else None, "token_id": token_id}
        for name, price, token_id in zip(names, prices, token_ids)
    ]
    return {
        "id": market.get("id"),
        "question": market.get("question"),
        "description": market.get("description"),
        "condition_id": market.get("conditionId"),
        "end_date": market.get("endDate"),
        "volume24hr": float(market.get("volume24hr") or 0),
        "liquidity": float(market.get("liquidity") or 0),
        "image": market.get("icon") or market.get("image"),
        "closed": bool(market.get("closed")),
        "accepting_orders": market.get("acceptingOrders", True),
        "outcomes": outcomes,
    }


def event_by_slug(slug: str) -> dict[str, Any] | None:
    events = _get(f"{config.GEMMA_API_BASE}/events", {"slug": normalise_slug(slug)})
    if not events:
        return None
    event = events[0]
    markets = [market_json(m) for m in event.get("markets") or [] if not m.get("closed")]
    markets.sort(key=lambda m: m["volume24hr"], reverse=True)
    return {
        "id": event.get("id"),
        "slug": event.get("slug"),
        "title": event.get("title"),
        "description": event.get("description"),
        "image": event.get("icon") or event.get("image"),
        "end_date": event.get("endDate"),
        "volume24hr": float(event.get("volume24hr") or 0),
        "markets": markets,
    }


def trending_events(tag: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "closed": "false", "active": "true", "limit": max(1, min(limit, 50)),
        "order": "volume24hr", "ascending": "false",
    }
    if tag:
        params["tag_slug"] = tag
    events = _get(f"{config.GEMMA_API_BASE}/events", params)
    return [{
        "id": e.get("id"),
        "slug": e.get("slug"),
        "title": e.get("title"),
        "image": e.get("icon") or e.get("image"),
        "volume24hr": float(e.get("volume24hr") or 0),
        "end_date": e.get("endDate"),
        "markets": len(e.get("markets") or []),
    } for e in events]


def price_history(token_id: str, interval: str = "1w") -> list[dict[str, float]]:
    if interval not in {"1d", "1w", "1m", "max"}:
        interval = "1w"
    fidelity = {"1d": 10, "1w": 60, "1m": 240, "max": 1440}[interval]
    data = _get(f"{config.CLOB_API_BASE}/prices-history",
                {"market": token_id, "interval": interval, "fidelity": fidelity})
    return [{"t": item["t"], "p": item["p"]} for item in data.get("history", [])]
