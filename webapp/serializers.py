"""Turn parsed logs (``log_store``) into JSON for the browser."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .log_store import Session, Step, ToolCall, Turn, session_summary

# Tool results above this size are sent as a truncated preview.
MAX_RESULT_CHARS = 200_000


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def media_url(session: Session, call: ToolCall) -> str | None:
    if call.image_path:
        return f"/media/{session.date}/{call.image_path}"
    return call.image_url


def call_json(session: Session, call: ToolCall) -> dict[str, Any]:
    result = call.result
    truncated = False
    if result is not None:
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            result, truncated = text[:MAX_RESULT_CHARS], True
    return {
        "call_id": call.call_id,
        "name": call.name,
        "status": call.status,
        "turn": call.turn,
        "step": call.step,
        "arguments": call.arguments,
        "result": result,
        "result_truncated": truncated,
        "result_type": call.result_type,
        "result_chars": call.result_chars,
        "image": media_url(session, call),
        "duration_ms": call.duration_ms,
        "start_ts": call.start_ts,
        "end_ts": call.end_ts,
        "error": call.error,
        "approval": call.approval,
        "approval_message": call.approval_message,
        "reasoning": call.reasoning,
    }


def step_json(session: Session, step: Step) -> dict[str, Any]:
    return {
        "turn": step.turn,
        "step": step.step,
        "start_ts": step.start_ts,
        "end_ts": step.end_ts,
        "duration_ms": step.duration_ms,
        "input_item_count": step.input_item_count,
        "usage": step.usage,
        "reasoning": step.reasoning,
        "reasoning_encrypted": any(o.get("type") == "reasoning" for o in step.outputs) and not step.reasoning,
        "messages": step.messages,
        "tools": [call_json(session, c) for c in step.tools],
    }


def turn_json(session: Session, turn: Turn) -> dict[str, Any]:
    return {
        "turn": turn.turn,
        "user_text": turn.user_text,
        "start_ts": turn.start_ts,
        "end_ts": turn.end_ts,
        "duration_ms": turn.duration_ms,
        "status": turn.status,
        "final_output": turn.final_output,
        "error": turn.error,
        "usage": turn.usage,
        "steps": [step_json(session, s) for s in turn.steps],
    }


def summary_json(session: Session) -> dict[str, Any]:
    summary = session_summary(session)
    summary["start"] = _iso(summary["start"])
    summary["end"] = _iso(summary["end"])
    summary["source"] = session.meta.get("source")
    summary["title"] = summary.get("first_message") or session.session_id
    return summary


def session_json(session: Session) -> dict[str, Any]:
    meta = session.meta
    return {
        "session_id": session.session_id,
        "date": session.date,
        "ended": session.ended,
        "summary": summary_json(session),
        "meta": {
            "model": meta.get("model"),
            "source": meta.get("source"),
            "reasoning": meta.get("reasoning"),
            "instructions": meta.get("instructions"),
            "tools": meta.get("tools") or [],
            "path": str(session.path),
        },
        "turns": [turn_json(session, t) for t in session.turns],
    }
