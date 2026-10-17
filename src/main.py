"""Interactive Polymarket trading chat powered by the OpenAI Agents SDK.

The Streamlit UI (``streamlit run viewer/view_app.py``) offers the same agent
with a richer interface; this module is the terminal version.
"""

from __future__ import annotations

import json
import os

from agent_runner import TradingChat, TurnResult


def ask_approvals(result: TurnResult) -> dict[str, bool]:
    """Ask in the terminal whether each pending live order may be placed."""
    decisions = {}
    for order in result.pending:
        print(f"\n⚠️  注文の承認が必要です: {order.tool}")
        print(json.dumps(order.arguments, ensure_ascii=False, indent=2))
        answer = input("この注文を発注しますか？ [y/N] ").strip().lower()
        decisions[order.call_id] = answer in {"y", "yes"}
    return decisions


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY を環境変数に設定してください。")

    chat = TradingChat(source="cli")
    print(f"ログ: {chat.log_path}")
    print("Polymarket trading agent. 終了するには exit または quit を入力してください。")

    try:
        while True:
            try:
                message = input("\nYou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n終了します。")
                return

            if message.lower() in {"exit", "quit"}:
                print("終了します。")
                return
            if not message:
                continue

            result = chat.send(message)
            while result.needs_approval:
                result = chat.resolve(ask_approvals(result))
            if result.error is not None:
                print(f"\nエラー: {result.error}")
            else:
                print(f"\nAgent> {result.final_output}")
    finally:
        chat.close()


if __name__ == "__main__":
    main()
