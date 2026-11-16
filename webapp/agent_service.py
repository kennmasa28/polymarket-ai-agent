"""Runs agent turns in background threads and streams their progress.

Each conversation is a :class:`agent_runner.TradingChat` identified by its log
session id.  A turn (a user message, or the user's decision on pending
orders) runs in a worker thread; every log record it writes is pushed to a
:class:`Run`, which the browser reads as Server-Sent Events.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .log_store import DEFAULT_LOG_DIR

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
# Fields too large or irrelevant for the live progress view.
_STREAM_DROP = {"result", "instructions", "tools", "traceback", "session_id"}
_RUN_TTL_SECONDS = 15 * 60


class ConflictError(RuntimeError):
    """The conversation cannot accept this action right now."""


def find_log(session_id: str, log_dir: Path = DEFAULT_LOG_DIR) -> Path | None:
    if not SESSION_ID_RE.match(session_id or ""):
        return None
    matches = sorted(Path(log_dir).glob(f"*/{session_id}.jsonl"))
    return matches[-1] if matches else None


class Run:
    """Progress events of one agent turn, readable from any position."""

    def __init__(self, conversation_id: str):
        self.id = uuid.uuid4().hex
        self.conversation_id = conversation_id
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.finished_at: float | None = None
        self._cond = threading.Condition()

    def push(self, record: dict[str, Any]) -> None:
        light = {k: v for k, v in record.items() if k not in _STREAM_DROP}
        with self._cond:
            self.events.append(light)
            self._cond.notify_all()

    def finish(self, payload: dict[str, Any]) -> None:
        with self._cond:
            self.events.append({"event": "run_done", **payload})
            self.done = True
            self.finished_at = time.time()
            self._cond.notify_all()

    def wait(self, index: int, timeout: float = 15.0) -> tuple[list[dict[str, Any]], bool]:
        """Events from ``index`` on (blocking up to ``timeout``) and whether the run ended."""
        with self._cond:
            if len(self.events) <= index and not self.done:
                self._cond.wait(timeout)
            return self.events[index:], self.done


class AgentService:
    def __init__(self, chat_factory: Callable[..., Any] | None = None):
        self._chat_factory = chat_factory
        self._chats: dict[str, Any] = {}
        self._active: dict[str, Run] = {}
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------- chats
    def _factory(self) -> Callable[..., Any]:
        if self._chat_factory is None:
            from agent_runner import TradingChat  # imported lazily: needs the trading SDK

            self._chat_factory = TradingChat
        return self._chat_factory

    def _get_chat(self, conversation_id: str | None, model: str | None, effort: str | None):
        if conversation_id and conversation_id in self._chats:
            chat = self._chats[conversation_id]
            if conversation_id not in self._active:
                chat.configure(model, effort)
            return chat
        log_path = None
        if conversation_id:
            log_path = find_log(conversation_id)
            if log_path is None:
                raise KeyError(conversation_id)
        chat = self._factory()(source="ui", log_path=log_path, model=model, reasoning_effort=effort)
        self._chats[chat.session_id] = chat
        return chat

    def pending(self, conversation_id: str) -> list[dict[str, Any]]:
        chat = self._chats.get(conversation_id)
        if chat is None:
            return []
        return [{"call_id": o.call_id, "tool": o.tool, "arguments": o.arguments} for o in chat.pending]

    def active_run(self, conversation_id: str) -> Run | None:
        return self._active.get(conversation_id)

    def close(self, conversation_id: str) -> None:
        with self._lock:
            if conversation_id in self._active:
                raise ConflictError("エージェントが実行中です。")
            chat = self._chats.pop(conversation_id, None)
        if chat is not None:
            chat.close()

    def close_all(self) -> None:
        for conversation_id in list(self._chats):
            try:
                self.close(conversation_id)
            except ConflictError:
                pass

    # ------------------------------------------------------------ runs
    def send(self, conversation_id: str | None, text: str, model: str | None = None,
             effort: str | None = None) -> Run:
        with self._lock:
            chat = self._get_chat(conversation_id, model, effort)
            if chat.session_id in self._active:
                raise ConflictError("エージェントが実行中です。完了を待ってください。")
            if chat.pending:
                raise ConflictError("承認待ちの注文があります。先に承認または却下してください。")
            run = self._register(chat)
        self._start(chat, run, lambda: chat.send(text))
        return run

    def resolve(self, conversation_id: str, decisions: dict[str, dict[str, Any]]) -> Run:
        with self._lock:
            chat = self._chats.get(conversation_id)
            if chat is None or not chat.pending:
                raise ConflictError("承認待ちの注文はありません。")
            if conversation_id in self._active:
                raise ConflictError("エージェントが実行中です。")
            missing = [o.call_id for o in chat.pending if o.call_id not in decisions]
            if missing:
                raise ConflictError("すべての注文について承認または却下を選んでください。")
            run = self._register(chat)
        approvals = {cid: bool(d.get("approve")) for cid, d in decisions.items()}
        notes = {cid: str(d["note"]) for cid, d in decisions.items() if d.get("note")}
        self._start(chat, run, lambda: chat.resolve(approvals, notes))
        return run

    def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def _register(self, chat) -> Run:
        self._gc_runs()
        run = Run(chat.session_id)
        self._active[chat.session_id] = run
        self._runs[run.id] = run
        return run

    def _gc_runs(self) -> None:
        now = time.time()
        for run_id, run in list(self._runs.items()):
            if run.finished_at and now - run.finished_at > _RUN_TTL_SECONDS:
                del self._runs[run_id]

    def _start(self, chat, run: Run, action: Callable[[], Any]) -> None:
        def work() -> None:
            chat.set_listener(run.push)
            payload: dict[str, Any]
            try:
                result = action()
                if result.error is not None:
                    payload = {"status": "error", "error": f"{type(result.error).__name__}: {result.error}"}
                elif result.needs_approval:
                    payload = {"status": "awaiting", "pending": self.pending(chat.session_id)}
                else:
                    output = result.final_output
                    payload = {"status": "done", "final_output": output if isinstance(output, str) else str(output)}
            except Exception as exc:  # never leave the browser waiting
                payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            finally:
                chat.set_listener(None)
                with self._lock:
                    self._active.pop(chat.session_id, None)
            run.finish(payload)

        threading.Thread(target=work, name=f"agent-{run.id[:8]}", daemon=True).start()
