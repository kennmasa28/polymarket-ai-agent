from trade import TRADE
from agent import Agent
import config
from pathlib import Path
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo


def main():
    tr = TRADE()
    ag = Agent()
    now_date = datetime.now().strftime("%Y/%m/%d")
    ## STEP 1: 現在の購入済トークンの状態を確認
    self_status = tr.get_self_status()

    for stat in self_status:
        full_log = ""
        full_log += f"==STEP 1==\n{stat}\n\n"
        ## STEP 2: トークン一つ一つについて、現在の情報を取得
        market_detail, token_info, img_base64 = tr.get_market_detail(market_id="", condition_id=stat['condition_id'])
        if int(stat['status']) == 0:
            status_text = """現在このマーケットでは、あなたの購入したトークンに損失が出ています。
            現在日付とマーケット終了日、今後トークン価値が上がりそうか総合的に考えて、このトークンを維持または売却を判断してください。
            迷ったら、維持を選択してください。回答は「維持」または「売却」のどちらか一言を回答してください。
            """
        else:
            status_text = """現在このマーケットでは、あなたの購入したトークンに利益が出ています。
            現在日付とマーケット終了日、最終的な予測が外れるリスクがあるかなど総合的に考えて、このトークンを維持または売却を判断してください。
            迷ったら、維持を選択してください。回答は「維持」または「売却」のどちらか一言を回答してください。"""
    

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
        print(llm_opinion)
        full_log += f"==STEP 2==\n{prompt}\n\n{llm_opinion}\n\n"

        # ===== full_log 保存（日付フォルダ分割） =====
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")

        # 日付ディレクトリ作成
        log_dir = Path("full_logs") / date_str
        log_dir.mkdir(parents=True, exist_ok=True)

        # ファイルパス生成
        log_path = log_dir / f"{time_str}_{stat['condition_id']}.txt"

        # 保存
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(str(full_log))

        if "売却" in llm_opinion:
            try:
                tlog_path = tr.make_book_order(stat['token'], float(stat["price"]), stat["size"], side="S")
                print(f"トークンを価格{stat['price']}で、{stat['size']}個売却しました。")
                print(f"Order response saved to: {tlog_path}")
            except:
                print(f"トークンを購入できませんでした。{log_path}を確認してください。")
        

if __name__=='__main__':
    main()