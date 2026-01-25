from trade import TRADE
from agent import Agent
import config
from pathlib import Path
import os
import json
from datetime import datetime


def main():
    tr = TRADE()
    ag = Agent()
    full_log = ""
    ## STEP 1: 参加イベントの候補を収集する。
    event_candidates = ""
    for tag in config.TREAT_EVENT_TAG_LIST:
        event_candidates += tr.get_recent_event_list(tag_slug=tag)
    full_log += f"==STEP 1==\n{event_candidates}\n\n"

    ## STEP 2: 詳細検討するイベントを一つ選び、その詳細を取得
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

        # 指示
        現在、以下のテーマで予測市場が開催されている。
        あなたが参加したいテーマ、予測に自信のあるテーマを一つ選び、そのイベントidを答えよ。

        # テーマ一覧
        {event_candidates}
    """

    event_id = ag.call_tool_to_show_detail_event(prompt=prompt)
    event_detail = tr.get_event_detail(event_id=event_id)
    full_log += f"==STEP 2==\n{prompt}\n\n{event_id}\n\n{event_detail}\n\n"

    ## STEP 3: 詳細検討するマーケットを一つ選び、その詳細を取得
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

        # 指示
        あなたは以下のテーマ（イベント）の予測市場に参加しようとしている。
        一つのテーマについて、複数のマーケットが開催されている。
        あなたが参加したいマーケット、予測に自信のあるマーケットを一つ選び、そのマーケットidを答えよ。

        # テーマ（イベント）の詳細
        {event_detail}
    """

    market_id = ag.call_tool_to_show_detail_market(prompt=prompt)
    market_detail, token_info, img_base64 = tr.get_market_detail(market_id=market_id)
    full_log += f"==STEP 3==\n{prompt}\n\n{market_id}\n\n{market_detail}\n\n"

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

        # 指示
        あなたは以下のテーマ（イベント）の予測市場に参加しようとしている。
        一つのテーマについて複数のマーケットが開催されており、あなたは以下のマーケットに参加する。
        マーケットのルール・詳細と、YES, NOトークンの価格推移画像を与えるので、あなたの意見を述べてください。
        関連するニュースがあれば、調べてください。
        ここではあなたの調査・意見表明のみ回答し、具体的にどちらのトークンにどれだけ賭けるかは答えなくてよい。

        # あなたが参加するテーマ（イベント）の詳細
        {event_detail}

        # あなたが参加するマーケットの詳細
        {market_detail}
    """

    llm_opinion = ag.get_LLM_opiniton(prompt=prompt, image_base64=img_base64)
    full_log += f"==STEP 4==\n{prompt}\n\n{llm_opinion}\n\n"

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

        # 指示
        あなたは以下のテーマ（イベント）の予測市場に参加しようとしている。
        一つのテーマについて複数のマーケットが開催されており、あなたは以下のマーケットに参加する。
        あなたが参加するマーケットの詳細、本マーケットに関する専門家の意見、Yes, Noトークンの価格推移画像を与えるので、Yes, Noのトークンをいくつ購入するか決定してください。
        出力はtoken, sizeの値を決定する形で出力せよ。
        token: Yes, Noのどちらのトークンを買うか。'Yes'または'No'で回答すること（先頭のみ大文字）。
        size: トークンをいくつ買うか、1-5の整数で回答せよ。自信があれば5に近く、自信がなければ1に近くせよ。

        # あなたが参加するマーケットの詳細
        {market_detail}

        # 本マーケットに関する付加情報
        {llm_opinion}
    """
    token, size = ag.call_tool_to_make_order(prompt=prompt, image_base64=img_base64)

    token_price = None
    for t in token_info:
        if t['token_name'] == token:
            token_id = t['token_id']
            token_price = t['token_price']
            size = int(size)
            token_price=float(token_price)
            break
    full_log += f"==STEP 5==\n{prompt}\n\n{token}\n{size}\n{token_price}\n\n"

    # full_logを保存
    log_dir = Path("full_logs")
    log_dir.mkdir(exist_ok=True)

    nowt = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{nowt}_{market_id}.txt"

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(str(full_log))
    
    if token_price is not None:
        try:
            log_path = tr.make_book_order(token_id, token_price, size)
            print(f"{token}トークンを価格{token_price}で、{size}個購入しました。")
            print(f"Order response saved to: {log_path}")
        except Exception as e:
            print(f"トークンを購入できませんでした。{e} {log_path}を確認してください。")
    else:
        print(f"トークンを購入できませんでした。{log_path}を確認してください。")

if __name__=='__main__':
    main()