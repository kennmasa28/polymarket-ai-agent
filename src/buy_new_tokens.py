from trade import TRADE
from agent import Agent
import config
from pathlib import Path
import os
import json
from datetime import datetime
import random
from zoneinfo import ZoneInfo

def summarize_event_and_market(eventdata, target_market_id):
    for event in eventdata:
        for market in event.get("markets", []):
            if market.get("market_id") == target_market_id:
                event_and_market_detail = {
                    "event": {
                        "event_id": event.get("event_id"),
                        "title": event.get("title"),
                        "description": event.get("description"),
                        "liquidity": event.get("liquidity"),
                        "volume": event.get("volume"),
                    },
                    "market": market
                }
    try:
        lines = []
        token_info = []
        lines.append(f"予測テーマ: {event_and_market_detail['market']['question']}")
        lines.append(f"詳細：{event_and_market_detail['event']['description']}")
        lines.append(f"終了日: {event_and_market_detail['market']['end_date']}")
        for i in range(len(event_and_market_detail['market']['token_name'])):
            lines.append(f" トークン「{event_and_market_detail['market']['token_name'][i]}」の価格：{event_and_market_detail['market']['token_price'][i]}")
            token_info.append({
                'token_name': event_and_market_detail['market']['token_name'][i],
                'token_id': event_and_market_detail['market']['token_ids'][i],
                'token_price': event_and_market_detail['market']['token_price'][i]
            })
        event_and_market_detail_text = "\n".join(lines)
        return event_and_market_detail_text, token_info
    except:
        return None, None  # 見つからなかった場合

def main(tag):
    tr = TRADE()
    ag = Agent()
    full_log = {}
    now_date = datetime.now().strftime("%Y/%m/%d")
    ## STEP 1: イベント・マーケットのリストを収集する。
    events_data = tr.get_recent_events_and_markets(tag_slug=tag, max_higher_price=config.MAX_HIGHER_PRICE)
    if events_data == []:
        events_data = tr.get_recent_events_and_markets(tag_slug=None, max_higher_price=config.MAX_HIGHER_PRICE)
    full_log["STEP1"] = f"{events_data}"

    ## STEP 2: 詳細検討するマーケットを一つ選ぶ
    lines = []
    events_data = json.loads(events_data)
    for event in events_data:
        markets = event.get("markets", [])
        for market in markets:
            lines.append(f"■ market_id: {market.get('market_id')}")
            lines.append(f" question: {market.get('question')}")
            lines.append(f" 終了日: {market.get('end_date')}")
            for i in range(len(market["token_name"])):
                lines.append(f" トークン「{market['token_name'][i]}」の価格：{market['token_price'][i]}")
            lines.append('---------')
    event_and_market_list_text = "\n".join(lines)
    prompt = f"""
        # 背景
        あなたは予測市場「Polymarket」に参加するトレーダーAIである。
        目的は 将来の事象の結果を確率的に予測し、期待値最大化となる取引判断を行うこと である。
        娯楽目的ではなく、合理的・確率論的・経済合理性に基づいて行動せよ。
        <Polymarketの基本構造>
        各マーケットは「はい（YES）」か「いいえ（NO）」で決着する二値事象である。
        YESとNOはそれぞれトークンとして取引され、価格は 0.00〜1.00 USD の範囲で推移する。
        価格は市場参加者の期待確率を反映している（例：YESが0.72 → 市場は72%の確率で起こると見ている）。
        決着時：
        事象が起きた場合、YESトークンは1.00 USD、NOは0.00 USDになる。
        起きなかった場合は逆。

        # 現在の日付
        {now_date}

        # 指示
        現在、以下のテーマで予測市場が開催されている。
        あなたが参加したいマーケット、予測に自信のあるマーケットを一つ選び、そのmarket_idを答えよ。
        特に、一般的な見解に対して市場の評価が適切でない（市場にゆがみがある）と思われるものは、積極的に狙うこと。

        # テーマ（イベント）の詳細
        {event_and_market_list_text}
    """

    market_id = ag.call_tool_to_show_detail_market(prompt=prompt)
    full_log["STEP2"] = {}
    full_log["STEP2"]["prompt"] = prompt
    full_log["STEP2"]["response"] = market_id

    ## STEP 3:マーケットの詳細情報を取得する。
    event_and_market_detail_text, token_info = summarize_event_and_market(events_data, market_id)
    img_path, img_base64 = tr.get_market_history_img(market_id=market_id)
    full_log["STEP3"] = str(img_path)

    ## STEP 4: LLMの意見を聞く
    prompt = f"""
        # 背景
        あなたは予測市場「Polymarket」に参加するトレーダーAIである。
        目的は 将来の事象の結果を確率的に予測し、期待値最大化となる取引判断を行うこと である。
        娯楽目的ではなく、合理的・確率論的・経済合理性に基づいて行動せよ。
        <Polymarketの基本構造>
        各マーケットは「はい（YES）」か「いいえ（NO）」で決着する二値事象である。
        YESとNOはそれぞれトークンとして取引され、価格は 0.00〜1.00 USD の範囲で推移する。
        価格は市場参加者の期待確率を反映している（例：YESが0.72 → 市場は72%の確率で起こると見ている）。
        決着時：
        事象が起きた場合、YESトークンは1.00 USD、NOは0.00 USDになる。
        起きなかった場合は逆。

        # 現在の日付
        {now_date}

        # 指示
        あなたは以下のテーマ（イベント）の予測市場に参加しようとしている。
        一つのテーマについて複数のマーケットが開催されており、あなたは以下のマーケットに参加する。
        マーケットのルール・詳細と、YES, NOトークンの価格推移画像を与えるので、あなたの意見を述べてください。
        関連するニュースがあれば、調べてください。
        ここではあなたの調査・意見表明のみ回答し、具体的にどちらのトークンにどれだけ賭けるかは答えなくてよい。

        # あなたが参加するマーケットの詳細
        {event_and_market_detail_text}
    """

    # llm_opinion = ag.get_LLM_opiniton(prompt=prompt, image_base64=img_base64)
    llm_opinion = "なし"
    full_log["STEP4"] = {}
    full_log["STEP4"]["prompt"] = prompt
    full_log["STEP4"]["response"] = llm_opinion

    ## STEP 5: 購入するトークンの種類の名前を取得 
    prompt = f"""
        # 背景
        あなたは予測市場「Polymarket」に参加するトレーダーAIである。
        目的は 将来の事象の結果を確率的に予測し、期待値最大化となる取引判断を行うこと である。
        娯楽目的ではなく、合理的・確率論的・経済合理性に基づいて行動せよ。
        <Polymarketの基本構造>
        各マーケットは「はい（YES）」か「いいえ（NO）」で決着する二値事象である。
        YESとNOはそれぞれトークンとして取引され、価格は 0.00〜1.00 USD の範囲で推移する。
        価格は市場参加者の期待確率を反映している（例：YESが0.72 → 市場は72%の確率で起こると見ている）。
        決着時：
        事象が起きた場合、YESトークンは1.00 USD、NOは0.00 USDになる。
        起きなかった場合は逆。

        # 現在の日付
        {now_date}

        # 指示
        あなたは以下のテーマ（イベント）の予測市場に参加しようとしている。
        一つのテーマについて複数のマーケットが開催されており、あなたは以下のマーケットに参加する。
        あなたが参加するマーケットの詳細、本マーケットに関する専門家の意見、Yes, Noトークンの価格推移画像を与えるので、Yes, Noのトークンをいくつ購入するか決定してください。
        出力はtoken, sizeの値を決定する形で出力せよ。
        token: Yes, Noのどちらのトークンを買うか。'Yes'または'No'で回答すること（先頭のみ大文字）。
        size: トークンをいくつ買うか、{config.MIN_BUY_TOKENS}-{config.MAX_BUY_TOKENS}の整数で回答せよ。自信があれば{config.MAX_BUY_TOKENS}に近く、自信がなければ{config.MIN_BUY_TOKENS}に近くせよ。

        # あなたが参加するマーケットの詳細
        {event_and_market_detail_text}

        # 本マーケットに関する専門家の意見
        {llm_opinion}
    """
    token, size = ag.call_tool_to_make_order(prompt=prompt, image_base64=img_base64)
    token_price = None
    for t in token_info:
        if t['token_name'] == token:
            token_id = t['token_id']
            token_price = min(t['token_price'] * config.BUY_BUFFER_RATE, config.MAX_HIGHER_PRICE)
            size = int(size)
            token_price=float(token_price)
            if size*token_price < 1.0:
                size = int(1.0/token_price) + 1
            break
    full_log["STEP5"] = {}
    full_log["STEP5"]["prompt"] = prompt
    full_log["STEP5"]["token"] = token
    full_log["STEP5"]["token_id"] = token_id
    full_log["STEP5"]["size"] = size
    full_log["STEP5"]["token_price"] = token_price

    # full_logを保存
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")

    # 日付ディレクトリ作成
    log_dir = Path("full_logs") / date_str
    log_dir.mkdir(parents=True, exist_ok=True)

    # ファイルパス生成
    log_path = log_dir / f"{time_str}_{market_id}.json"
    
    if token_price is not None:
        try:
            tlog_path = tr.make_book_order(token_id, token_price, size, side="B")
            print(f"{token}トークンを価格{token_price}で、{size}個購入しました。")
            print(f"Order response saved to: {tlog_path}")
            full_log["STEP5"]["result"] = "成功"
        except Exception as e:
            print(f"トークンを購入できませんでした。{e} {log_path}を確認してください。")
            full_log["STEP5"]["result"] = "失敗"
    else:
        print(f"トークンを購入できませんでした。{log_path}を確認してください。")
        full_log["STEP5"]["result"] = "失敗"
    
    # full_logを保存
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(full_log, f, ensure_ascii=False, indent=2)

if __name__=='__main__':
    tag = random.choice(config.TREAT_EVENT_TAG_LIST)
    main(tag)