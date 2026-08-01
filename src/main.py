"""Interactive Polymarket trading chat powered by the OpenAI Agents SDK."""

from __future__ import annotations

import os

from agents import Agent, Runner, SQLiteSession

import config
from slills_loader import skills_as_instructions
from tools import TRADING_TOOLS


BASE_INSTRUCTIONS = """You are a Polymarket token trading assistant.
Respond in Japanese unless the user requests another language.  You may use
the portfolio tool to inspect the account.  Buy and sell tools place LIVE
orders: before calling either, state the token ID, direction, amount/shares,
and material execution risk, then obtain an explicit confirmation from the
user in the current conversation.  Never invent a token ID, position, price,
or tool result.  Do not provide financial advice; present information and let
the user decide.
"""


def create_agent() -> Agent:
    """Create the trading agent with all Markdown skills loaded as guidance."""
    instructions = f"{BASE_INSTRUCTIONS}\n\n# Local skills\n{skills_as_instructions()}"
    return Agent(
        name="Polymarket Trading Agent",
        model=config.MODEL,
        instructions=instructions,
        tools=TRADING_TOOLS,
    )


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY を環境変数に設定してください。")

    agent = create_agent()
    session = SQLiteSession("polymarket-trading-chat")
    print("Polymarket trading agent. 終了するには exit または quit を入力してください。")

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

        try:
            result = Runner.run_sync(agent, message, session=session)
            print(f"\nAgent> {result.final_output}")
        except Exception as exc:
            print(f"\nエラー: {exc}")


if __name__ == "__main__":
    main()
