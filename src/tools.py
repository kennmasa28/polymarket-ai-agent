"""LLM tools that safely adapt the project's Polymarket trade client."""

from __future__ import annotations

import json
from typing import Any

from agents import ToolOutputImage, function_tool

from trade import TRADE


def _serialise_result(result: Any) -> str:
    """Produce a tool result that is always valid JSON for the model."""
    return json.dumps(result, ensure_ascii=False, default=str)


@function_tool
def get_portfolio_status() -> str:
    """Get the connected Polymarket account's current token positions.

    Returns each position's market title, outcome token ID, quantity, current
    value, average purchase price, and unrealized profit/loss.
    """
    return _serialise_result(TRADE().get_self_status())


@function_tool
def get_recent_event_list(
    limit: int = 20,
    tag_slug: str | None = None,
    volume_min: int = 10000,
    max_months_ahead: int = 6,
) -> str:
    """Get active Polymarket events, ordered by 24-hour trading volume.

    Args:
        limit: Maximum number of events to return.
        tag_slug: Optional event-category tag slug, such as ``ai``.
        volume_min: Minimum 24-hour volume for returned events.
        max_months_ahead: Include events ending no later than this many months ahead.
    """
    return _serialise_result(
        TRADE().get_recent_event_list(
            limit=limit,
            tag_slug=tag_slug,
            volume_min=volume_min,
            max_months_ahead=max_months_ahead,
        )
    )


@function_tool
def get_particular_event_by_id(event_id: int) -> str:
    """Get an event and the markets belonging to it.

    Args:
        event_id: Polymarket event ID obtained from ``get_recent_event_list``.
    """
    return _serialise_result(TRADE().get_particular_event_by_id(event_id))


@function_tool
def get_market_by_conditionid(condition_id: str) -> str:
    """Get a market's question, outcomes, prices, and outcome token IDs.

    Args:
        condition_id: Polymarket condition ID obtained from event market data.
    """
    if not condition_id.strip():
        raise ValueError("condition_id must not be empty")
    return TRADE().get_market_by_conditionid(condition_id)


@function_tool
def get_market_history_image(condition_id: str) -> ToolOutputImage:
    """Return a market's outcome-token price history as a PNG chart.

    Args:
        condition_id: Polymarket condition ID identifying the market.

    The image plots all outcome token prices returned for the market. Use this
    tool when the user asks to inspect a market's price movement or trend.
    """
    if not condition_id.strip():
        raise ValueError("condition_id must not be empty")

    _, image_base64 = TRADE().get_market_history_img_by_condition_id(condition_id)
    return ToolOutputImage(image_url=f"data:image/png;base64,{image_base64}")


@function_tool
def buy_token(token_id: str, amount_usd: int) -> str:
    """Place a live market BUY order for a Polymarket outcome token.

    Args:
        token_id: The outcome token ID obtained from portfolio or market data.
        amount_usd: Whole-number USDC amount to spend; must be positive.

    This submits a real FAK market order and writes an order log.
    """
    if amount_usd <= 0:
        raise ValueError("amount_usd must be a positive integer")
    return _serialise_result(TRADE().make_buy_order(token_id, amount_usd, "BUY"))


@function_tool
def sell_token(token_id: str, shares: int) -> str:
    """Place a live market SELL order for a Polymarket outcome token.

    Args:
        token_id: The outcome token ID to sell.
        shares: Whole number of outcome shares to sell; must be positive.

    This submits a real FAK market order and writes an order log.
    """
    if shares <= 0:
        raise ValueError("shares must be a positive integer")
    return _serialise_result(TRADE().make_sell_order(token_id, shares, "SELL"))


TRADING_TOOLS = [
    get_portfolio_status,
    get_recent_event_list,
    get_particular_event_by_id,
    get_market_by_conditionid,
    get_market_history_image,
    buy_token,
    sell_token,
]
