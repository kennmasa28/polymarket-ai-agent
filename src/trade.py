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
from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

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

    def get_recent_event_list(self, limit: int = 20, tag_slug=None, volume_min: int = 10000, max_months_ahead: int = 6):
        now = datetime.now(timezone.utc)
        some_months_later = (now + relativedelta(months=max_months_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{self.gemma_api_base}/events"
        params = {
            "closed": "false",
            "active": "true",
            "limit": limit,
            "offset": 0,
            "tag_slug": tag_slug,
            "order": "volume24hr",
            "volume_min": volume_min,
            "end_date_max": some_months_later,
            "ascending": "false",
        }
        events = self.get(url, params=params)
        return events
    
    def get_market_by_conditionid(self, condition_id):
        url = f"{self.gemma_api_base}/markets"
        params = {
            "condition_ids": [condition_id],
        }
        markets = self.get(url, params=params)
        marketdata = []
        for market in markets:
            market_id = int(market.get('id'))
            condition_id = f"{market.get('conditionId')}"
            question = f"{market.get('question')}"
            detail = market.get('description')
            tokenname = market.get('outcomes')
            tokenprice = market.get('outcomePrices')
            token_ids = market.get('clobTokenIds')
            enddate = f"{market.get('endDate')}"
            tokenname = json.loads(tokenname)
            tokenprice = json.loads(tokenprice)
            tokenprice = [float(p) for p in tokenprice]   
            token_ids = json.loads(token_ids)
            marketdata.append({
                "market_id": market_id,
                "condition_id": condition_id,
                "question": question,
                "description": detail,
                "token_name": tokenname,
                "token_price": tokenprice,
                "token_ids": token_ids,
                "end_date": enddate
            })
        
        return json.dumps(marketdata, ensure_ascii=False, indent=2)


    def get_recent_events_and_markets(self, tag_slug=None, volume_min=10000, max_months_ahead=6, max_higher_price=0.90):
        events = self.get_recent_event_list(tag_slug=tag_slug, 
                                            volume_min = volume_min, 
                                            max_months_ahead=max_months_ahead)
        eventdata = []
        for event in events:
            event_id = int(event.get('id'))
            title = f"{event.get('title')}"
            detail = f" {event.get('description')}"
            liquidity = float(event.get('liquidity', 0))
            volume = float(event.get('volume', 0))
            markets = event.get("markets", [])
            marketdata = []
            for market in markets:
                market_id = int(market.get('id'))
                condition_id = f"{market.get('conditionId')}"
                question = f"{market.get('question')}"
                market_volume = float(market.get('volume', 0))
                tokenname = market.get('outcomes')
                tokenprice = market.get('outcomePrices')
                token_ids = market.get('clobTokenIds')
                enddate = f"{market.get('endDate')}"
                """
                Yes, No以外のトークンがあるものは除去
                高い方の勝率がmax_higher_price以上のものは除去
                """
                if tokenname is not None:
                    tokenname = json.loads(tokenname)
                    if 'Yes' not in tokenname[0]:
                        continue
                else:
                    continue
                if tokenprice is not None:
                    tokenprice = json.loads(tokenprice)
                    tokenprice = [float(p) for p in tokenprice]
                    if max(tokenprice) > max_higher_price:
                        continue
                else:
                    continue
                if token_ids is not None:
                    token_ids = json.loads(token_ids)
                else:
                    continue

                marketdata.append({
                    "market_id": market_id,
                    "condition_id": condition_id,
                    "question": question,
                    "volume": market_volume,
                    "token_name": tokenname,
                    "token_price": tokenprice,
                    "token_ids": token_ids,
                    "end_date": enddate
                })
            if len(marketdata) == 0:
                continue
            eventdata.append({
                "event_id": event_id,
                "title": title,
                "description": detail.strip(),
                "liquidity": liquidity,
                "volume": volume,
                "markets": marketdata
            })

        return json.dumps(eventdata, ensure_ascii=False, indent=2)
    
    def get_market_history_img(self, market_id: str, condition_id: str=""):
        if condition_id == "":
            url = f"{self.gemma_api_base}/markets/{market_id}"
            market = self.get(url)
        else:
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
        img_path = img_dir / f"{time_str}_{market_id}.png"

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
    
    def make_book_order(self, token_id: str, price: float, size: int, side: str):
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

        if side == "B":
            resp = client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=BUY,
                )
            )
        else:
            resp = client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=SELL,
                )
            )

        # ===== ログ保存処理（日付フォルダ分割） =====
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")

        # 日付ディレクトリ作成
        log_dir = Path("transaction_logs") / date_str
        log_dir.mkdir(parents=True, exist_ok=True)

        # ファイルパス生成
        log_path = log_dir / f"{time_str}.txt"

        # 保存
        with open(log_path, "w", encoding="utf-8") as f:
            if isinstance(resp, (dict, list)):
                json.dump(resp, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(resp))

        return log_path
    
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


if __name__=='__main__':
    t = TRADE()
    # print(t.get_recent_event_list(tag_slug="ai"))
    # print(t.get_event_detail(156613))
    # print(t.get_market_detail(1345937))
    # id = t.get_self_status()
    print(id)



