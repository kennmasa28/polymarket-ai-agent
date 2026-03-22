from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from zoneinfo import ZoneInfo

import config
from trade import TRADE

POLL_INTERVAL_SECONDS = config.POLL_INTERVAL_SECONDS
MIDPOINT_BATCH_SIZE = config.MIDPOINT_BATCH_SIZE
CONSECUTIVE_DECREASE_THRESHOLD = config.CONSECUTIVE_DECREASE_THRESHOLD


class OwnTokenPriceTracker:
    def __init__(self) -> None:
        self.clob_api_base = config.CLOB_API_BASE
        self.session = requests.Session()
        self.price_history: dict[str, list[float]] = {}
        self.tr = TRADE()

    def post(self, url: str, *, payload: list[dict[str, Any]]) -> Any:
        response = self.session.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

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
        print(f"tracking own positions every {POLL_INTERVAL_SECONDS} seconds")

        while True:
            positions = self.tr.get_self_status()
            active_token_ids = {position["token_id"] for position in positions}
            self._prune_history(active_token_ids)

            if not positions:
                print(f"[{self._utc_now()}] no open positions")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            midpoints = self.fetch_midpoints([position["token_id"] for position in positions])
            snapshot = {
                "timestamp": self._utc_now(),
                "position_count": len(positions),
                "positions": [],
                "alerts": [],
            }

            for position in positions:
                midpoint = midpoints.get(position["token_id"])
                current_price = float(midpoint) if midpoint is not None else position["price"]

                alert = self._update_price_history_and_detect_alert(
                    position=position,
                    current_price=current_price,
                )
                if alert is not None:
                    snapshot["alerts"].append(alert)

                snapshot["positions"].append(
                    {
                        "condition_id": position["condition_id"],
                        "token_name": position["token_name"],
                        "token_id": position["token_id"],
                        "size": position["size"],
                        "average_price": position["avr_price"],
                        "current_price": current_price,
                    }
                )

            if snapshot["alerts"]:
                self._sell_alert_positions(snapshot["alerts"])

            time.sleep(POLL_INTERVAL_SECONDS)

    def _sell_alert_positions(self, alerts: list[dict[str, Any]]) -> None:
        full_log: dict[str, Any] = {}
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")
        log_dir = Path("full_logs") / date_str
        log_dir.mkdir(parents=True, exist_ok=True)

        for alert in alerts:
            condition_id = alert["condition_id"]
            full_log[condition_id] = {
                "condition_id": condition_id,
                "token": alert["token_name"],
                "token_id": alert["token_id"],
                "size": alert["size"],
                "token_price": alert["sell_price"],
                "prices": alert["prices"],
                "decrease_rates": alert["decrease_rates"],
            }

            try:
                tlog_path = self.tr.make_book_order(
                    alert["token_id"],
                    alert["sell_price"],
                    alert["size"],
                    side="S",
                )
                print(
                    f"{alert['token_name']}を価格{alert['sell_price']}で、{alert['size']}個売却しました。"
                )
                print(f"Order response saved to: {tlog_path}")
                full_log[condition_id]["result"] = "成功"
                full_log[condition_id]["transaction_log_path"] = str(tlog_path)
            except Exception as exc:
                print(f"{alert['token_name']}を売却できませんでした。{exc}")
                full_log[condition_id]["result"] = "失敗"
                full_log[condition_id]["error"] = str(exc)

        log_path = log_dir / f"{time_str}_sell_alerts.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(full_log, f, ensure_ascii=False, indent=2)

    def _update_price_history_and_detect_alert(
        self,
        *,
        position: dict[str, Any],
        current_price: float | None,
    ) -> dict[str, Any] | None:
        token_id = position["token_id"]

        if current_price is None or current_price <= 0:
            self.price_history.pop(token_id, None)
            return None

        history = self.price_history.setdefault(token_id, [])
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
            first_change <= -CONSECUTIVE_DECREASE_THRESHOLD
            and second_change <= -CONSECUTIVE_DECREASE_THRESHOLD
        ):
            sell_price = max(third * config.SELL_BUFFER_RATE, 0.01)
            self.price_history.pop(token_id, None)
            return {
                "condition_id": position["condition_id"],
                "token_name": position["token_name"],
                "token_id": token_id,
                "size": position["size"],
                "prices": [first, second, third],
                "decrease_rates": [first_change, second_change],
                "sell_price": sell_price,
                "message": (
                    f"{position['token_name']} price decreased by threshold twice consecutively"
                ),
            }

        return None

    def _prune_history(self, active_token_ids: set[str]) -> None:
        stale_token_ids = [
            token_id for token_id in self.price_history if token_id not in active_token_ids
        ]
        for token_id in stale_token_ids:
            self.price_history.pop(token_id, None)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    tracker = OwnTokenPriceTracker()
    tracker.poll_forever()
