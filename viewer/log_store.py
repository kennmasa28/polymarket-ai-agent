"""Read and structure the JSONL logs written by ``src/agent_logger.py``.

Pure Python (no Streamlit) so that it can be reused from scripts or tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = Path(os.getenv("POLYVIEWER_LOG_DIR") or Path(__file__).resolve().parent.parent / "agent_logs")

# USD per 1M tokens: (input, cached input, output).  Editable from the sidebar.
DEFAULT_PRICES = (1.25, 0.125, 10.0)

TOKEN_KEYS = ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "total_tokens")


def read_events(path: Path | str) -> list[dict[str, Any]]:
    """Read a JSONL log; a partially written last line is skipped."""
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def list_log_files(log_dir: Path | str) -> list[Path]:
    """All session logs, newest first."""
    root = Path(log_dir)
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*.jsonl"), key=lambda p: p.name, reverse=True)


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def cost_usd(usage: dict[str, Any] | None, prices: tuple[float, float, float] = DEFAULT_PRICES) -> float:
    if not usage:
        return 0.0
    p_in, p_cached, p_out = prices
    cached = usage.get("cached_tokens", 0) or 0
    uncached = max((usage.get("input_tokens", 0) or 0) - cached, 0)
    return (uncached * p_in + cached * p_cached + (usage.get("output_tokens", 0) or 0) * p_out) / 1e6


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: Any = None
    turn: int = 0
    step: int = 0
    start_ts: str | None = None
    end_ts: str | None = None
    duration_ms: int | None = None
    result: Any = None
    result_type: str | None = None
    result_chars: int | None = None
    image_path: str | None = None
    image_url: str | None = None
    error: dict[str, Any] | None = None
    reasoning: list[str] = field(default_factory=list)  # reasoning that led to this call
    approval: str | None = None  # None (not required) / "pending" / "approved" / "rejected"
    approval_message: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.approval == "rejected":
            return "rejected"
        if self.approval == "pending":
            return "awaiting"
        if self.end_ts is None:
            return "running"
        return "ok"


@dataclass
class Step:
    """One LLM call and the tool calls it requested."""

    turn: int
    step: int
    start_ts: str | None = None
    end_ts: str | None = None
    duration_ms: int | None = None
    input_item_count: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    outputs: list[dict[str, Any]] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)

    @property
    def reasoning(self) -> list[str]:
        texts = []
        for o in self.outputs:
            if o.get("type") == "reasoning":
                texts += [t for t in o.get("summary", []) + o.get("content", []) if t]
        return texts

    @property
    def messages(self) -> list[str]:
        return [o.get("text", "") for o in self.outputs if o.get("type") == "message"]


@dataclass
class Turn:
    turn: int
    user_text: str = ""
    start_ts: str | None = None
    end_ts: str | None = None
    steps: list[Step] = field(default_factory=list)
    final_output: Any = None
    duration_ms: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    @property
    def tools(self) -> list[ToolCall]:
        return [t for s in self.steps for t in s.tools]

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.final_output is None:
            return "awaiting" if any(c.status == "awaiting" for c in self.tools) else "running"
        return "ok"


@dataclass
class Session:
    path: Path
    session_id: str
    events: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)
    ended: bool = False

    @property
    def date(self) -> str:
        return self.path.parent.name

    @property
    def start(self) -> datetime | None:
        return parse_ts(self.events[0]["ts"]) if self.events else None

    @property
    def end(self) -> datetime | None:
        return parse_ts(self.events[-1]["ts"]) if self.events else None

    @property
    def steps(self) -> list[Step]:
        return [s for t in self.turns for s in t.steps]

    @property
    def tools(self) -> list[ToolCall]:
        return [c for t in self.turns for c in t.tools]

    def usage_total(self) -> dict[str, int]:
        total = {k: 0 for k in TOKEN_KEYS}
        for s in self.steps:
            for k in TOKEN_KEYS:
                total[k] += s.usage.get(k, 0) or 0
        return total

    def image_file(self, call: ToolCall) -> Path | None:
        return self.path.parent / call.image_path if call.image_path else None


def build_session(path: Path | str, events: list[dict[str, Any]] | None = None) -> Session:
    path = Path(path)
    events = events if events is not None else read_events(path)
    session = Session(path=path, session_id=path.stem, events=events)

    turns: dict[int, Turn] = {}
    steps: dict[tuple[int, int], Step] = {}
    calls: dict[str, ToolCall] = {}

    def get_turn(n: int) -> Turn:
        if n not in turns:
            turns[n] = Turn(turn=n)
        return turns[n]

    def get_step(t: int, s: int) -> Step:
        key = (t, s)
        if key not in steps:
            steps[key] = Step(turn=t, step=s)
            get_turn(t).steps.append(steps[key])
        return steps[key]

    def get_call(ev: dict[str, Any]) -> ToolCall:
        cid = ev.get("call_id") or f"unknown-{len(calls)}"
        if cid not in calls:
            step = get_step(ev.get("turn", 0), ev.get("step", 0))
            calls[cid] = ToolCall(
                call_id=cid, name=ev.get("tool") or "?", turn=ev.get("turn", 0), step=ev.get("step", 0),
                reasoning=step.reasoning,
            )
            step.tools.append(calls[cid])
        return calls[cid]

    for ev in events:
        kind = ev.get("event")
        turn_no = ev.get("turn", 0)
        if kind == "session_start":
            session.meta = ev
        elif kind == "session_end":
            session.ended = True
        elif kind == "session_resume":
            session.ended = False
        elif kind == "approval_request":
            c = get_call(ev)
            c.arguments = ev.get("arguments")
            c.approval = "pending"
        elif kind == "approval_decision":
            c = get_call(ev)
            c.approval = "approved" if ev.get("approved") else "rejected"
            c.approval_message = ev.get("message")
        elif kind == "user_message":
            t = get_turn(turn_no)
            t.user_text = ev.get("text", "")
            t.start_ts = ev.get("ts")
        elif kind == "llm_start":
            s = get_step(turn_no, ev.get("step", 0))
            s.start_ts = ev.get("ts")
            s.input_item_count = ev.get("input_item_count")
        elif kind == "llm_end":
            s = get_step(turn_no, ev.get("step", 0))
            s.end_ts = ev.get("ts")
            s.duration_ms = ev.get("duration_ms")
            s.usage = ev.get("usage") or {}
            s.response_id = ev.get("response_id")
            s.outputs = ev.get("outputs") or []
        elif kind == "tool_start":
            c = get_call(ev)
            c.arguments = ev.get("arguments")
            c.start_ts = ev.get("ts")
        elif kind == "tool_end":
            c = get_call(ev)
            c.end_ts = ev.get("ts")
            c.duration_ms = ev.get("duration_ms")
            c.result = ev.get("result")
            c.result_type = ev.get("result_type")
            c.result_chars = ev.get("result_chars")
            c.image_path = ev.get("image_path")
            c.image_url = ev.get("image_url")
        elif kind == "tool_error":
            c = get_call(ev)
            c.error = {k: ev.get(k) for k in ("error_type", "error", "traceback")}
            if c.arguments is None:
                c.arguments = ev.get("arguments")
        elif kind == "final_output":
            t = get_turn(turn_no)
            t.final_output = ev.get("text")
            t.end_ts = ev.get("ts")
            t.duration_ms = ev.get("duration_ms")
            t.usage = ev.get("usage") or {}
        elif kind == "run_error":
            t = get_turn(turn_no)
            t.error = {k: ev.get(k) for k in ("error_type", "error", "traceback")}
            t.end_ts = ev.get("ts")
            t.duration_ms = ev.get("duration_ms")

    # Reasoning is attached to tool calls when the call is first seen; llm_end
    # always precedes tool_start, but refresh in case of reordering.
    for s in steps.values():
        for c in s.tools:
            c.reasoning = s.reasoning

    session.turns = [turns[k] for k in sorted(turns) if k > 0]
    return session


def session_summary(session: Session, prices: tuple[float, float, float] = DEFAULT_PRICES) -> dict[str, Any]:
    usage = session.usage_total()
    tools = session.tools
    start, end = session.start, session.end
    first = next((t.user_text for t in session.turns if t.user_text), "")
    return {
        "date": session.date,
        "session_id": session.session_id,
        "start": start,
        "end": end,
        "duration_s": (end - start).total_seconds() if start and end else None,
        "model": session.meta.get("model", "?"),
        "turns": len(session.turns),
        "llm_calls": len(session.steps),
        "tool_calls": len(tools),
        "tool_errors": sum(1 for c in tools if c.error),
        "run_errors": sum(1 for t in session.turns if t.error),
        "trades": sum(1 for c in tools if c.name in ("buy_token", "sell_token")),
        **usage,
        "cost_usd": sum(cost_usd(s.usage, prices) for s in session.steps),
        "first_message": first,
        "live": not session.ended,
        "path": str(session.path),
    }
