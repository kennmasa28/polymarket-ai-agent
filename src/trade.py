from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import requests
import config
import json
from pathlib import Path
from matplotlib import pyplot as plt
from datetime import datetime
import matplotlib.dates as mdates
import base64
from io import BytesIO
import os
from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY

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

        # セッションを使うとコネクション再利用できる（任意）
        self.session = requests.Session()

    def get(self, url: str, *, params: Optional[dict[str, Any]] = None) -> Any:
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_recent_event_list(self, limit: int = 20, tag_slug=None, volume_min: int = 10000):
        url = f"{self.gemma_api_base}/events"
        params = {
            "closed": "false",
            "active": "true",
            "limit": limit,
            "offset": 0,
            "tag_slug": tag_slug,
            "order": "id",
            "volume_min": volume_min,
            "ascending": "false",
        }
        events = self.get(url, params=params)
        lines = []
        for event in events:
            lines.append(f"■ イベントid: {event['id']}")
            lines.append(f" タイトル: {event['title']}")
            lines.append(f"------------")
        summary_text = "\n".join(lines)
        return summary_text
        
    
    def get_event_detail(self, event_id: str):
        url = f"{self.gemma_api_base}/events/{event_id}"
        events = self.get(url)
        lines = []
        lines.append("■ イベント基本情報")
        lines.append(f" id: {events.get('id')}")
        lines.append(f" slug: {events.get('slug')}")
        lines.append(f" タイトル: {events.get('title')}")
        lines.append(f" 詳細: {events.get('description')}")
        lines.append(f" 終了日: {events.get('endDate')}")
        lines.append(f" アクティブか: {events.get('active')}")

        if 'liquidity' in events:
            lines.append(f" 流動性: {events['liquidity']}")
        if 'volume' in events:
            lines.append(f" 掛金総額: {events['volume']}")

        markets = events.get("markets", [])
        lines.append(f" マーケットの数: {len(markets)}")

        for market in markets:
            lines.append(f"■ マーケットID: {market.get('id')}")
            lines.append(f" conditionId: {market.get('conditionId')}")
            lines.append(f" question: {market.get('question')}")
            if 'volume' in market:
                lines.append(f" 掛金総額: {market['volume']}")
            lines.append(f" トークン名: {market.get('outcomes')}")
            lines.append(f" 価格: {market.get('outcomePrices')}")

        summary_text = "\n".join(lines)
        return summary_text
    
    def get_market_detail(self, market_id: str):
        url = f"{self.gemma_api_base}/markets/{market_id}"
        market = self.get(url)
        lines = []
        lines.append(f"■ マーケットID: {market.get('id')}")
        lines.append(f" conditionId: {market.get('conditionId')}")
        lines.append(f" question: {market.get('question')}")
        if 'volume' in market:
            lines.append(f" 掛金総額: {market['volume']}")
        lines.append(f" トークン名: {market.get('outcomes')}")
        lines.append(f" 価格: {market.get('outcomePrices')}")
        summary_text = "\n".join(lines)
        token_info = []
        token_name = json.loads(market.get('outcomes'))
        token_id = json.loads(market.get('clobTokenIds'))
        token_price = json.loads(market.get('outcomePrices'))
        timeseries = {}
        """
        トークン情報を取得
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
        # 画像を保存
        img_dir = Path("img_logs")
        img_dir.mkdir(exist_ok=True)
        nowt = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = img_dir / f"{nowt}_{market_id}.png"
        plt.savefig(img_path, format="png", bbox_inches="tight")
        # 画像をメモリに保存
        buf = BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close()  # メモリリーク防止
        buf.seek(0)
        # base64 エンコード
        img_base64 = base64.b64encode(buf.read()).decode("utf-8")
        
        return summary_text, token_info, img_base64
    
    def make_book_order(self, token_id: str, price: float, size: int):
        signer = Account.from_key(self.private_key).address

        temp_client = ClobClient(self.clob_api_base, 
                                 key=self.private_key, 
                                 chain_id=self.chain_id, 
                                 funder=self.funder, 
                                 signature_type=2)
        api_creds = temp_client.create_or_derive_api_creds()

        client = ClobClient(self.clob_api_base, 
                            key=self.private_key, 
                            chain_id=self.chain_id, 
                            creds=api_creds, 
                            funder=self.funder, 
                            signature_type=2)

        resp = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY,
            )
        )
        # ===== ログ保存処理 =====
        log_dir = Path("transaction_logs")
        log_dir.mkdir(exist_ok=True)

        nowt = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"{nowt}.txt"

        with open(log_path, "w", encoding="utf-8") as f:
            if isinstance(resp, (dict, list)):
                json.dump(resp, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(resp))

        return log_path


if __name__=='__main__':
    t = TRADE()
    print(t.get_event_detail(156613))
    print(t.get_market_detail(1157582))

