from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import requests
import config
import json
from pathlib import Path
from matplotlib import pyplot as plt
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
import matplotlib.dates as mdates
import base64
from io import BytesIO
import os
from zoneinfo import ZoneInfo
from polymarket import SecureClient

class TRADE:
    """
    共通のAPI基盤（HTTPクライアント + 設定）
    """
    def __init__(self):
        self.funder = config.FUNDER
        self.private_key = config.PRIVATE_KEY
        self.gemma_api_base = config.GEMMA_API_BASE
        self.clob_api_base = config.CLOB_API_BASE
        self.data_api_base = config.DATA_API_BASE
        self.chain_id = config.CHAIN_ID
        self.client = SecureClient.create(
            private_key=self.private_key,
            wallet=self.funder,
        )

        # セッションを使うとコネクション再利用できる（任意）
        self.session = requests.Session()

    def get(self, url: str, *, params: Optional[dict[str, Any]] = None) -> Any:
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    
    def get_self_status(self):
        url = f"{self.data_api_base}/positions"
        params = {
            "user": self.funder,
        }
        data = self.get(url, params=params)
        self_status = []

        for dat in data:
            condition_id = dat['conditionId']
            delta =  dat['currentValue'] - dat['size'] * dat['avgPrice']
            lines = []
            lines.append(f"タイトル: {dat['title']}")
            lines.append(f"あなたの所持トークン: {dat['outcome']}")
            lines.append(f"あなたのトークン保有数: {dat['size']}")
            lines.append(f"あなたのトークン購入時の平均買値(単価): ${dat['avgPrice']}")
            lines.append(f"現在のトークン価値(単価): ${dat['currentValue'] / dat['size']}")
            lines.append(f"あなたがトークン購入に費やした総額: ${dat['size'] * dat['avgPrice']}")
            lines.append(f"今このトークンをすべて売却すると得られるお金: ${dat['currentValue']}")
            lines.append(f"予想が当たった時、このトークンと交換できるお金: ${dat['size'] * 1.0}")
            summary_text = "\n".join(lines)
            self_status.append({
                "condition_id": condition_id,
                "delta": delta,
                "text": summary_text,
                "token_name": dat['outcome'],
                "token_id": dat["asset"],
                "size": float(dat['size']),
                "price": float(dat['currentValue'] / dat['size']),
                "avr_price": float(dat['avgPrice'])
            })
        return self_status

    def save_order_log(self, order_log: dict, token_id:str, side:str):
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")
        log_dir = Path("../order_logs") / date_str
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{time_str}_{side}_{token_id}.json"
        with log_path.open("w", encoding="utf-8") as log_file:
            json.dump(order_log, log_file, ensure_ascii=False, indent=2, default=str)

    def make_buy_order(self, token_id: str, amount: int, side: str):
        with self.client:
            order = self.client.create_market_order(
                token_id=token_id,
                side=side,
                amount=amount,
                order_type="FAK",
            )
            estimated_price = self.client.estimate_market_price(
                token_id=token_id, side=side, amount=amount, order_type="FAK"
            )
            # 注文を送信
            response = self.client.post_order(order)
            
            order_log = {
                "tokenId": order.token_id,
                "side": order.side,
                "orderType": order.order_type,
                "estimatedPrice": estimated_price,
                "maker": order.maker,
                "makerAmount": order.maker_amount,
                "takerAmount": order.taker_amount,
                "response": response,
            }
            self.save_order_log(order_log, token_id, side)
            
        return response

    def make_sell_order(self, token_id: str, shares: int, side: str):
        with self.client:
            order = self.client.create_market_order(
                token_id=token_id,
                side=side,
                shares=shares,
                order_type="FAK",
            )
            # 注文を送信
            estimated_price = self.client.estimate_market_price(
                token_id=token_id, side=side, shares=shares, order_type="FAK"
            )
            response = self.client.post_order(order)
            
            order_log = {
                "tokenId": order.token_id,
                "side": order.side,
                "orderType": order.order_type,
                "estimatedPrice": estimated_price,
                "maker": order.maker,
                "makerAmount": order.maker_amount,
                "takerAmount": order.taker_amount,
                "response": response,
            }
            self.save_order_log(order_log, token_id, side)
            
        return response

    def get_market_history_img_by_condition_id(self, condition_id: str=""):
        # if condition_id == "":
        #     url = f"{self.gemma_api_base}/markets/{market_id}"
        #     market = self.get(url)
        # else:
        #     url = f"{self.gemma_api_base}/markets?condition_ids={condition_id}"
        #     market = self.get(url)[0]
        url = f"{self.gemma_api_base}/markets?condition_ids={condition_id}"
        market = self.get(url)[0]
        token_info = []
        token_name = json.loads(market.get('outcomes'))
        token_id = json.loads(market.get('clobTokenIds'))
        token_price = json.loads(market.get('outcomePrices'))
        """
        トークンの価格履歴を図示
        """
        ts = {}
        plt.figure()
        for i in range(len(token_name)):
            token_info.append({
                'token_name': token_name[i],
                'token_id': token_id[i],
                'token_price': token_price[i]
            })
            url = f"{self.clob_api_base}/prices-history"
            params = {
                        "market": token_id[i],
                        "interval": '6h'
                    }
            data = self.get(url, params=params)
            ts['time'] = []
            ts[token_name[i]] = []
            for item in data["history"]:
                ts["time"].append(datetime.utcfromtimestamp(item["t"])) 
                ts[token_name[i]].append(item["p"])
            plt.plot(ts['time'], ts[token_name[i]], label=token_name[i])
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45)
        plt.title(f"{market.get('question')}")
        plt.xlabel('time')
        plt.ylabel('price of tokens')
        plt.legend()
        plt.tight_layout()
        # 画像を保存（日付フォルダ分割）
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")

        # 日付ディレクトリ作成
        img_dir = Path("img_logs") / date_str
        img_dir.mkdir(parents=True, exist_ok=True)

        # ファイル名生成
        img_path = img_dir / f"{time_str}_{condition_id}.png"

        # 保存
        plt.savefig(img_path, format="png", bbox_inches="tight")
        # 画像をメモリに保存
        buf = BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close()  # メモリリーク防止
        buf.seek(0)
        # base64 エンコード
        img_base64 = base64.b64encode(buf.read()).decode("utf-8")
        
        return img_path, img_base64
