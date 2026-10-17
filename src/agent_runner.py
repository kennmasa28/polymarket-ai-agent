"""Shared trading-agent runtime used by the CLI (``main.py``) and the Streamlit UI.

Buy/sell tools are declared with ``needs_approval=True``, so a run stops
before any live order is placed.  :class:`TradingChat` exposes those pending
orders and resumes the run once the user approves or rejects each of them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agents import Agent, ModelSettings, Runner, SQLiteSession
from openai.types.shared import Reasoning

import config
from agent_logger import DEFAULT_LOG_DIR, AgentLogger, _parse_json
from slills_loader import skills_as_instructions
from tools import TRADING_TOOLS

# Conversation memory of every chat, keyed by the log's session id, so that a
# conversation can be reopened after the app restarts.
MEMORY_DB = DEFAULT_LOG_DIR / "chat_memory.db"

BASE_INSTRUCTIONS = """You are a Polymarket token trading assistant.
Respond in Japanese unless the user requests another language.  You may use
the portfolio tool to inspect the account.  Buy and sell tools place LIVE
orders: before calling either, state the token ID, direction, amount/shares,
and material execution risk.  Every buy/sell call is shown to the user for
approval by the application before it is executed; if the user rejects it,
do not retry the same order unless asked.  Never claim an order was placed
unless the tool result says it succeeded.  Never invent a token ID, position,
price, or tool result.  Do not provide financial advice; present information
and let the user decide.
"""


def create_agent(model: str | None = None, reasoning_effort: str | None = None) -> Agent:
    """Create the trading agent with all Markdown skills loaded as guidance."""
    instructions = f"{BASE_INSTRUCTIONS}\n\n# Local skills\n{skills_as_instructions()}"
    return Agent(
        name="Polymarket Trading Agent",
        model=model or config.MODEL,
        instructions=instructions,
        tools=TRADING_TOOLS,
        # Request reasoning summaries so that the model's reasoning is logged.
        model_settings=ModelSettings(
            reasoning=Reasoning(
                effort=reasoning_effort or config.REASONING_EFFORT, summary=config.REASONING_SUMMARY
            )
        ),
    )


@dataclass
class PendingOrder:
    """A buy/sell tool call waiting for the user's decision."""

    call_id: str
    tool: str
    arguments: dict[str, Any]
    item: Any = field(repr=False)  # the SDK's ToolApprovalItem


@dataclass
class TurnResult:
    final_output: Any = None
    pending: list[PendingOrder] = field(default_factory=list)
    error: Exception | None = None

    @property
    def needs_approval(self) -> bool:
        return bool(self.pending)


class TradingChat:
    """One conversation: agent memory, step-by-step log and pending approvals."""

    def __init__(
        self,
        source: str = "cli",
        log_path: Path | str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        listener: Callable[[dict[str, Any]], None] | None = None,
        memory_db: Path | str = MEMORY_DB,
    ):
        self.model = model or config.MODEL
        self.reasoning_effort = reasoning_effort
        self.agent = create_agent(self.model, reasoning_effort)
        self.logger = AgentLogger(path=log_path, listener=listener)
        self.logger.log_session_start(self.agent, source=source)
        Path(memory_db).parent.mkdir(parents=True, exist_ok=True)
        self.memory = SQLiteSession(self.logger.session_id, str(memory_db))
        self._state = None  # RunState of an interrupted run
        self.pending: list[PendingOrder] = []
        if self.logger.resumed:
            self._close_orphan_calls("前回のセッション終了時に未承認だったため取り消されました。")

    @property
    def session_id(self) -> str:
        return self.logger.session_id

    @property
    def log_path(self) -> Path:
        return self.logger.path

    def configure(self, model: str | None = None, reasoning_effort: str | None = None) -> None:
        """Switch model settings for the following turns (memory is kept)."""
        model = model or config.MODEL
        if (model, reasoning_effort) != (self.model, self.reasoning_effort) and not self.pending:
            self.model, self.reasoning_effort = model, reasoning_effort
            self.agent = create_agent(model, reasoning_effort)

    def set_listener(self, listener: Callable[[dict[str, Any]], None] | None) -> None:
        self.logger.listener = listener

    # ------------------------------------------------------------------ turns
    def send(self, message: str) -> TurnResult:
        if self.pending:
            raise RuntimeError("承認待ちの注文があります。先に承認または却下してください。")
        self.logger.log_user_message(message)
        return self._run(message)

    def resolve(self, decisions: dict[str, bool], messages: dict[str, str] | None = None) -> TurnResult:
        """Approve (True) or reject (False) each pending order by call id, then resume."""
        if self._state is None:
            raise RuntimeError("承認待ちの注文はありません。")
        messages = messages or {}
        for order in self.pending:
            approved = decisions.get(order.call_id, False)
            note = messages.get(order.call_id) or None
            if approved:
                self._state.approve(order.item)
            else:
                self._state.reject(
                    order.item,
                    rejection_message=note and f"ユーザーが注文を却下しました: {note}"
                    or "ユーザーがこの注文を却下しました。",
                )
            self.logger.log_approval_decision(order.call_id, order.tool, approved, note)
        state, self._state, self.pending = self._state, None, []
        return self._run(state)

    def cancel_pending(self, reason: str = "ユーザーが会話を離れたため注文は取り消されました。") -> None:
        """Drop pending orders without resuming the run (e.g. when leaving the chat)."""
        if not self.pending:
            return
        for order in self.pending:
            self.logger.log_approval_decision(order.call_id, order.tool, False, reason)
        self._state, self.pending = None, []
        self._close_orphan_calls(reason, log=False)

    def _close_orphan_calls(self, reason: str, log: bool = True) -> None:
        """Give every tool call in memory without an output a cancellation output.

        An interrupted run stores the model's ``function_call`` in memory; if
        it is never resumed, the next request would be rejected by the API.
        """
        items = asyncio.run(self.memory.get_items())
        answered = {i.get("call_id") for i in items if i.get("type") == "function_call_output"}
        orphans = [i for i in items if i.get("type") == "function_call" and i.get("call_id") not in answered]
        if not orphans:
            return
        asyncio.run(self.memory.add_items([
            {"type": "function_call_output", "call_id": i["call_id"], "output": reason} for i in orphans
        ]))
        if log:
            for i in orphans:
                self.logger.log_approval_decision(i["call_id"], i.get("name"), False, reason)

    def _run(self, run_input: Any) -> TurnResult:
        try:
            result = Runner.run_sync(self.agent, run_input, session=self.memory, hooks=self.logger)
        except Exception as exc:
            self.logger.log_run_error(exc)
            return TurnResult(error=exc)

        if result.interruptions:
            self._state = result.to_state()
            self.pending = []
            for item in result.interruptions:
                raw = item.raw_item
                call_id = getattr(raw, "call_id", None) or (raw.get("call_id") if isinstance(raw, dict) else None)
                args = getattr(raw, "arguments", None) or (raw.get("arguments") if isinstance(raw, dict) else None)
                parsed = _parse_json(args)
                order = PendingOrder(
                    call_id=call_id or "", tool=item.tool_name or "?",
                    arguments=parsed if isinstance(parsed, dict) else {"arguments": parsed}, item=item,
                )
                self.pending.append(order)
                self.logger.log_approval_request(order.call_id, order.tool, order.arguments)
            return TurnResult(pending=list(self.pending))

        self.logger.log_final_output(result.final_output, result.context_wrapper.usage)
        return TurnResult(final_output=result.final_output)

    def close(self) -> None:
        self.cancel_pending()
        self.logger.log_session_end()
