from trade import TRADE
from agent import Agent
import config
from pathlib import Path
import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def summarize_event_and_market(marketdata):
    try:
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

def judge_rulebase(stat):
    delta_rate = stat["delta"]/stat["size"]/stat["avr_price"]
    # ほぼ当たりなら、さっさと売る
    if stat["price"] > 0.95:
        return "機械判断：売却 価格0.95以上"
    if delta_rate > 3.0:
        return "機械判断：売却 価格3倍以上"
    if abs(delta_rate) < 0.1:
        return "機械判断：維持 価格変化なし"
    return "LLMに任せる"


def main():
    tr = TRADE()
    ag = Agent()
    now_date = datetime.now().strftime("%Y/%m/%d")
    self_status = tr.get_self_status()

    for stat in self_status:
        full_log = {}
        ## STEP 1: 現在の購入済トークンの状態を確認
        market_data = tr.get_market_by_conditionid(stat["condition_id"])
        market_detail, _ = summarize_event_and_market(market_data)
        full_log["STEP1"] = {}
        full_log["STEP1"]["stat"] = f"{stat}"
        full_log["STEP1"]["market_data"] = f"{market_data}"

        ## STEP 2: トークンの売却維持判断を機械で
        judge_rulebase_result = judge_rulebase(stat)
        full_log["STEP2"] = judge_rulebase_result
        if "LLM" in judge_rulebase_result:
            ## STEP 3: トークンのHistoryを取得
            img_path, img_base64 = tr.get_market_history_img(market_id="", condition_id=stat['condition_id'])
            full_log["STEP3"] = str(img_path)
            if stat['delta'] < 0:
                status_text = f"""現在このマーケットでは、あなたの購入したトークンに{float(stat['delta'])}ドルの損失が出ています。
                現在日付とマーケット終了日、今後トークン価値が上がりそうか総合的に考えて、このトークンを維持または売却を判断してください。
                <判断のポイント>
                - 一般的知見から推測される確率（価格）対して、市場に歪みがあると感じる場合は維持する
                - 価格が減少傾向にあり、逆転の可能性に乏しい場合は売却する
                回答は「維持」または「売却」のどちらか一言を回答してください。
                """
            else:
                status_text = f"""現在このマーケットでは、あなたの購入したトークンに{float(stat['delta'])}ドルの利益が出ています。
                現在日付とマーケット終了日、最終的な予測が外れるリスクがあるかなど総合的に考えて、このトークンを維持または売却を判断してください。
                <判断のポイント>
                - 一般的知見から推測される確率（価格）対して、市場に歪みがあると感じる場合は売却する
                - 今後、価格が大きく揺れ動きそうなケースでは売却する
                - 価格が安定している場合は維持する
                回答は「維持」または「売却」のどちらか一言を回答してください。"""
        
            ## STEP 4: トークンの売却維持判断
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
                以下は、あなたが過去に注文したマーケットの詳細と、あなたの購入したトークンに関する情報です。
                {status_text}

                # あなたが参加するマーケットの詳細
                {market_detail}

                # あなたの購入済トークンについて
                {stat["text"]}
        """

            llm_opinion = ag.get_LLM_opiniton(prompt=prompt, image_base64=img_base64)
            full_log["STEP4"] = {}
            full_log["STEP4"]["prompt"] = f"{prompt}"
            full_log["STEP4"]["response"] = f"{llm_opinion}"
        else:
            llm_opinion = judge_rulebase_result
            full_log["STEP3"] = None
            full_log["STEP4"] = None

        # ===== full_log 保存（日付フォルダ分割） =====
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")

        # 日付ディレクトリ作成
        log_dir = Path("full_logs") / date_str
        log_dir.mkdir(parents=True, exist_ok=True)

        # ファイルパス生成
        log_path = log_dir / f"{time_str}_{stat['condition_id']}.json"


        if "売却" in llm_opinion:
            size = stat["size"]
            token = stat["token_name"]
            token_id = stat['token_id']
            price = float(stat["price"]) * config.SELL_BUFFER_RATE
            full_log["STEP5"] = {}
            full_log["STEP5"]["token"] = token
            full_log["STEP5"]["token_id"] = token_id
            full_log["STEP5"]["size"] = size
            full_log["STEP5"]["token_price"] = price
            try:
                tlog_path = tr.make_book_order(token_id, price, size, side="S")
                print(f"トークンを価格{stat['price']}で、{stat['size']}個売却しました。")
                print(f"Order response saved to: {tlog_path}")
                full_log["STEP5"]["result"] = "成功"
            except:
                print(f"トークンを売却できませんでした。{log_path}を確認してください。")
                full_log["STEP5"]["result"] = "失敗"
        else:
            full_log["STEP5"] = None
            print("トークンを維持しました")
        # full_logを保存
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(full_log, f, ensure_ascii=False, indent=2)
        

if __name__=='__main__':
    main()