from __future__ import annotations
from trade import TRADE
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import requests
import config
from zoneinfo import ZoneInfo
from pathlib import Path

POLL_INTERVAL_SECONDS = config.POLL_INTERVAL_SECONDS
TOP_MARKET_COUNT = config.TOP_MARKET_COUNT
MARKET_REFRESH_EVERY = config.MARKET_REFRESH_EVERY
GAMMA_PAGE_SIZE = config.GAMMA_PAGE_SIZE
MIDPOINT_BATCH_SIZE = config.MIDPOINT_BATCH_SIZE
CONSECUTIVE_INCREASE_THRESHOLD = config.CONSECUTIVE_INCREASE_THRESHOLD

@dataclass
class MarketToken:
    token_id: str
    outcome: str


@dataclass
class MarketInfo:
    market_id: str
    condition_id: str
    question: str
    slug: str | None
    liquidity: float
    volume: float
    end_date: str | None
    tokens: list[MarketToken]

def summarize_event_and_market(marketdata):
    try:
        marketdata = json.loads(marketdata)[0]
        print(marketdata)
        lines = []
        token_info = []
        lines.append(f"予測テーマ: {marketdata['question']}")
        lines.append(f"詳細：{marketdata['description']}")
        lines.append(f"終了日: {marketdata['end_date']}")
        for i in range(len(marketdata['token_name'])):
            lines.append(f" トークン「{marketdata['token_name'][i]}」の価格：{marketdata['token_price'][i]}")
            token_info.append({
                'token_name': marketdata['token_name'][i],
                'token_id': marketdata['token_ids'][i],
                'token_price': marketdata['token_price'][i]
            })
        market_detail_text = "\n".join(lines)
        return market_detail_text, token_info
    except:
        return None, None  # 見つからなかった場合

class PolymarketPriceTracker:
    def __init__(self) -> None:
        self.gamma_api_base = config.GEMMA_API_BASE
        self.clob_api_base = config.CLOB_API_BASE
        self.session = requests.Session()
        self.price_history: dict[str, list[float]] = {}
        self.tr = TRADE()

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def post(self, url: str, *, payload: list[dict[str, Any]]) -> Any:
        response = self.session.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_open_markets(self, max_pages: int = 5) -> list[dict[str, Any]]:
        markets: list[dict[str, Any]] = []
        url = f"{self.gamma_api_base}/markets"

        for page in range(max_pages):
            params = {
                "active": "true",
                "closed": "false",
                "limit": GAMMA_PAGE_SIZE,
                "offset": page * GAMMA_PAGE_SIZE,
                "order": "volume24hr"
            }
            page_items = self.get(url, params=params)
            if not page_items:
                break
            markets.extend(page_items)
            if len(page_items) < GAMMA_PAGE_SIZE:
                break

        return markets

    def build_market_universe(self) -> list[MarketInfo]:
        raw_markets = self.fetch_open_markets()
        candidates: list[MarketInfo] = []

        for market in raw_markets:
            if not market.get("active") or market.get("closed"):
                continue
            if not market.get("enableOrderBook"):
                continue

            outcomes_raw = market.get("outcomes")
            token_ids_raw = market.get("clobTokenIds")
            if not outcomes_raw or not token_ids_raw:
                continue

            try:
                outcomes = json.loads(outcomes_raw)
                token_ids = json.loads(token_ids_raw)
            except (TypeError, json.JSONDecodeError):
                continue

            if len(outcomes) != len(token_ids) or len(token_ids) < 2:
                continue

            tokens = [
                MarketToken(token_id=str(token_id), outcome=str(outcome))
                for outcome, token_id in zip(outcomes, token_ids)
            ]

            liquidity = self._to_float(
                market.get("liquidityNum", market.get("liquidity", 0))
            )
            volume = self._to_float(
                market.get("volumeNum", market.get("volume", 0))
            )

            candidates.append(
                MarketInfo(
                    market_id=str(market.get("id")),
                    condition_id=str(market.get("conditionId")),
                    question=str(market.get("question") or ""),
                    slug=market.get("slug"),
                    liquidity=liquidity,
                    volume=volume,
                    end_date=market.get("endDate"),
                    tokens=tokens,
                )
            )

        candidates.sort(key=lambda item: item.liquidity, reverse=True)
        return candidates[:TOP_MARKET_COUNT]

    def fetch_midpoints(self, token_ids: list[str]) -> dict[str, str]:
        url = f"{self.clob_api_base}/midpoints"
        results: dict[str, str] = {}

        for start in range(0, len(token_ids), MIDPOINT_BATCH_SIZE):
            batch = token_ids[start : start + MIDPOINT_BATCH_SIZE]
            payload = [{"token_id": token_id} for token_id in batch]
            batch_result = self.post(url, payload=payload)
            if isinstance(batch_result, dict):
                results.update(batch_result)

        return results

    def poll_forever(self) -> None:
        cycle = 0
        markets = self.build_market_universe()

        if not markets:
            raise RuntimeError("open markets could not be loaded from Polymarket API")

        print(
            f"tracking {len(markets)} markets every {POLL_INTERVAL_SECONDS} seconds"
        )

        while True:
            cycle += 1

            if cycle == 1 or cycle % MARKET_REFRESH_EVERY == 0:
                markets = self.build_market_universe()
                print(
                    f"[{self._utc_now()}] refreshed market universe: {len(markets)} markets"
                )

            token_ids = [token.token_id for market in markets for token in market.tokens]
            midpoints = self.fetch_midpoints(token_ids)

            snapshot = {
                "timestamp": self._utc_now(),
                "market_count": len(markets),
                "markets": [],
                "alerts": [],
            }

            for rank, market in enumerate(markets, start=1):
                prices = {}
                for token in market.tokens:
                    midpoint = midpoints.get(token.token_id)
                    current_price = float(midpoint) if midpoint is not None else None
                    prices[token.outcome] = current_price

                    alert = self._update_price_history_and_detect_alert(
                        market=market,
                        token=token,
                        current_price=current_price,
                    )
                    if alert is not None:
                        snapshot["alerts"].append(alert)
                snapshot["markets"].append(
                    {
                        "rank": rank,
                        "market_id": market.market_id,
                        "condition_id": market.condition_id,
                        "question": market.question,
                        "slug": market.slug,
                        "liquidity": market.liquidity,
                        "volume": market.volume,
                        "end_date": market.end_date,
                        "prices": prices,
                    }
                )

            # print(json.dumps(snapshot, ensure_ascii=False))
            # アラートが鳴った場合
            if snapshot["alerts"] != []:
                full_log = {}
                now = datetime.now(ZoneInfo("Asia/Tokyo"))
                date_str = now.strftime("%Y%m%d")
                time_str = now.strftime("%H%M%S")
                log_dir = Path("full_logs") / date_str
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / f"{time_str}_★.json"
                print(snapshot["timestamp"])
                for market in snapshot["alerts"]:
                    ## STEP 1: 現在の購入済トークンの状態を確認
                    market_data = self.tr.get_market_by_conditionid(market["condition_id"])
                    _, token_info = summarize_event_and_market(market_data)
                    for ti in token_info:
                        if ti["token_id"] == market["token_id"]:
                            size = max(1.01/ ti["token_price"], 5.0)
                            token = ti["token_name"]
                            token_id = ti['token_id']
                    price = float(ti["token_price"]) * config.BUY_BUFFER_RATE
                    full_log[market["condition_id"]] = {}
                    full_log[market["condition_id"]]["token"] = token
                    full_log[market["condition_id"]]["token_id"] = token_id
                    full_log[market["condition_id"]]["size"] = size
                    full_log[market["condition_id"]]["token_price"] = price
                    full_log[market["condition_id"]]["increase_rates"] = market["increase_rates"]
                    try:
                        tlog_path = self.tr.make_book_order(token_id, price, size, side="B")
                        print(f"トークンを価格{price}で、{size}個購入しました。")
                        print(f"Order response saved to: {tlog_path}")
                        full_log[market["condition_id"]]["result"] = "成功"
                    except:
                        print(f"トークンを購入できませんでした。{log_path}を確認してください。")
                        full_log[market["condition_id"]]["result"] = "失敗"
                    
                # full_logを保存
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(full_log, f, ensure_ascii=False, indent=2)

            time.sleep(POLL_INTERVAL_SECONDS)

    def _update_price_history_and_detect_alert(
        self,
        *,
        market: MarketInfo,
        token: MarketToken,
        current_price: float | None,
    ) -> dict[str, Any] | None:
        if current_price is None or current_price <= 0:
            self.price_history.pop(token.token_id, None)
            return None

        history = self.price_history.setdefault(token.token_id, [])
        history.append(current_price)
        if len(history) > 3:
            history.pop(0)

        if len(history) < 3:
            return None

        first, second, third = history
        if first <= 0 or second <= 0:
            return None

        first_change = (second - first) / first
        second_change = (third - second) / second
        if (
            first_change >= CONSECUTIVE_INCREASE_THRESHOLD
            and second_change >= CONSECUTIVE_INCREASE_THRESHOLD
        ):
            return {
                "market_id": market.market_id,
                "condition_id": market.condition_id,
                "question": market.question,
                "slug": market.slug,
                "outcome": token.outcome,
                "token_id": token.token_id,
                "prices": [first, second, third],
                "increase_rates": [first_change, second_change],
                "message": (
                    f"{token.outcome} price increased by 5%+ twice consecutively"
                ),
            }

        return None

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    tracker = PolymarketPriceTracker()
    tracker.poll_forever()
