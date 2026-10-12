"""Step-by-step JSONL logging of agent behaviour for ``viewer/view_app.py``.

Every run writes one file per chat session:
``agent_logs/<YYYY-MM-DD>/<session_id>.jsonl``.  Each line is one event, and
the file is flushed after every write so that the viewer can follow a session
while it is still running and nothing is lost if the process crashes.

Event types (``event`` field):
    session_start  model, instructions, tool schemas
    user_message   user's input for a turn
    llm_start      an LLM request is about to be sent
    llm_end        LLM response: reasoning summaries, tool calls, messages, usage
    tool_start     a local tool is invoked with its arguments
    tool_end       the tool's return value (images are saved as PNG files)
    tool_error     the exception raised inside a tool (with traceback)
    final_output   the agent's final answer for the turn
    run_error      an exception that aborted the turn
    session_end    the chat session finished
"""

from __future__ import annotations

import base64
import json
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agents import Agent, RunContextWrapper, RunHooks, Tool, ToolOutputImage
from agents.items import ModelResponse, TResponseInputItem

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "agent_logs"

# The logger currently attached to a run; used by ``tool_failure_handler``,
# which the Agents SDK calls without access to the hooks object.
_active_logger: AgentLogger | None = None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _to_jsonable(value: Any) -> Any:
    """Convert SDK / pydantic objects into plain JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump(exclude_none=True))
    return str(value)


def _parse_json(text: Any) -> Any:
    """Return parsed JSON when ``text`` is a JSON string, otherwise ``text``."""
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _summarise_output_item(item: Any) -> dict[str, Any]:
    """Extract the fields worth analysing from one Responses output item."""
    raw = _to_jsonable(item)
    if not isinstance(raw, dict):
        return {"type": "unknown", "raw": raw}

    item_type = raw.get("type")
    if item_type == "reasoning":
        return {
            "type": "reasoning",
            "id": raw.get("id"),
            "summary": [s.get("text", "") for s in raw.get("summary", []) or []],
            "content": [c.get("text", "") for c in raw.get("content", []) or []],
            "encrypted": bool(raw.get("encrypted_content")),
        }
    if item_type == "function_call":
        return {
            "type": "function_call",
            "call_id": raw.get("call_id"),
            "name": raw.get("name"),
            "arguments": _parse_json(raw.get("arguments")),
        }
    if item_type == "message":
        texts = []
        for part in raw.get("content", []) or []:
            if part.get("type") == "output_text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "refusal":
                texts.append(f"[refusal] {part.get('refusal', '')}")
        return {"type": "message", "text": "\n".join(texts)}
    return {"type": item_type or "unknown", "raw": raw}


def _usage_dict(usage: Any) -> dict[str, int]:
    in_details = getattr(usage, "input_tokens_details", None)
    out_details = getattr(usage, "output_tokens_details", None)
    return {
        "requests": getattr(usage, "requests", 0) or 0,
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "cached_tokens": getattr(in_details, "cached_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "reasoning_tokens": getattr(out_details, "reasoning_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


def _describe_tool(tool: Tool) -> dict[str, Any]:
    return {
        "name": getattr(tool, "name", str(tool)),
        "description": getattr(tool, "description", ""),
        "parameters": _to_jsonable(getattr(tool, "params_json_schema", None)),
    }


class AgentLogger(RunHooks):
    """Run hooks that append every agent step to a JSONL file."""

    def __init__(self, log_dir: Path | str = DEFAULT_LOG_DIR, session_id: str | None = None):
        global _active_logger

        started = datetime.now()
        self.session_id = session_id or f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.day_dir = Path(log_dir) / f"{started:%Y-%m-%d}"
        self.image_dir = self.day_dir / "images"
        self.day_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.day_dir / f"{self.session_id}.jsonl"
        self._file = self.path.open("a", encoding="utf-8")

        self.turn = 0
        self.step = 0
        self._turn_started = 0.0
        self._llm_started = 0.0
        self._tool_started: dict[str, float] = {}
        _active_logger = self

    # ------------------------------------------------------------------ core
    def write(self, event: str, **fields: Any) -> None:
        record = {
            "ts": _now(),
            "session_id": self.session_id,
            "event": event,
            "turn": self.turn,
            "step": self.step,
            **{k: _to_jsonable(v) for k, v in fields.items()},
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    # ------------------------------------------------- called from main.py
    def log_session_start(self, agent: Agent) -> None:
        reasoning = getattr(agent.model_settings, "reasoning", None)
        self.write(
            "session_start",
            agent=agent.name,
            model=str(agent.model),
            reasoning=reasoning,
            instructions=agent.instructions if isinstance(agent.instructions, str) else None,
            tools=[_describe_tool(t) for t in agent.tools],
        )

    def log_user_message(self, text: str) -> None:
        self.turn += 1
        self.step = 0
        self._turn_started = time.perf_counter()
        self.write("user_message", text=text)

    def log_final_output(self, output: Any, usage: Any = None) -> None:
        self.write(
            "final_output",
            text=output if isinstance(output, str) else _to_jsonable(output),
            duration_ms=self._elapsed_ms(self._turn_started),
            usage=_usage_dict(usage) if usage is not None else None,
        )

    def log_run_error(self, exc: BaseException) -> None:
        self.write(
            "run_error",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=self._elapsed_ms(self._turn_started),
        )

    def log_session_end(self) -> None:
        self.write("session_end")
        self._file.close()

    # ------------------------------------------------------------ run hooks
    async def on_agent_start(self, context: Any, agent: Agent) -> None:
        self.write("agent_start", agent=agent.name)

    async def on_llm_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        self.step += 1
        self._llm_started = time.perf_counter()
        self.write(
            "llm_start",
            agent=agent.name,
            input_item_count=len(input_items),
            system_prompt_chars=len(system_prompt or ""),
        )

    async def on_llm_end(self, context: RunContextWrapper, agent: Agent, response: ModelResponse) -> None:
        self.write(
            "llm_end",
            agent=agent.name,
            duration_ms=self._elapsed_ms(self._llm_started),
            response_id=response.response_id,
            usage=_usage_dict(response.usage),
            outputs=[_summarise_output_item(item) for item in response.output],
        )

    async def on_tool_start(self, context: RunContextWrapper, agent: Agent, tool: Tool) -> None:
        call_id = getattr(context, "tool_call_id", None) or f"tool-{uuid.uuid4().hex[:8]}"
        self._tool_started[call_id] = time.perf_counter()
        self.write(
            "tool_start",
            call_id=call_id,
            tool=getattr(tool, "name", str(tool)),
            arguments=_parse_json(getattr(context, "tool_arguments", None)),
        )

    async def on_tool_end(self, context: RunContextWrapper, agent: Agent, tool: Tool, result: object) -> None:
        call_id = getattr(context, "tool_call_id", None) or ""
        started = self._tool_started.pop(call_id, None)
        self.write(
            "tool_end",
            call_id=call_id,
            tool=getattr(tool, "name", str(tool)),
            duration_ms=self._elapsed_ms(started) if started else None,
            **self._serialise_tool_result(call_id, result),
        )

    async def on_handoff(self, context: RunContextWrapper, from_agent: Agent, to_agent: Agent) -> None:
        self.write("handoff", from_agent=from_agent.name, to_agent=to_agent.name)

    async def on_agent_end(self, context: Any, agent: Agent, output: Any) -> None:
        self.write("agent_end", agent=agent.name)

    # -------------------------------------------------------------- helpers
    def log_tool_error(self, context: RunContextWrapper, error: Exception) -> None:
        self.write(
            "tool_error",
            call_id=getattr(context, "tool_call_id", None),
            tool=getattr(context, "tool_name", None),
            arguments=_parse_json(getattr(context, "tool_arguments", None)),
            error_type=type(error).__name__,
            error=str(error),
            traceback="".join(traceback.format_exception(error)),
        )

    def _serialise_tool_result(self, call_id: str, result: object) -> dict[str, Any]:
        """Return log fields for a tool result, saving images to disk."""
        image = None
        if isinstance(result, ToolOutputImage):
            image = result.image_url
        elif isinstance(result, dict) and result.get("type") == "image":
            image = result.get("image_url")

        if image and image.startswith("data:image/"):
            header, _, data = image.partition(",")
            ext = header.split("/")[1].split(";")[0] or "png"
            self.image_dir.mkdir(parents=True, exist_ok=True)
            image_path = self.image_dir / f"{self.session_id}_{call_id}.{ext}"
            image_path.write_bytes(base64.b64decode(data))
            return {
                "result_type": "image",
                "image_path": str(image_path.relative_to(self.day_dir)),
                "result_chars": len(data),
            }
        if image:
            return {"result_type": "image", "image_url": image, "result_chars": len(image)}

        if isinstance(result, str):
            parsed = _parse_json(result)
            return {
                "result_type": "json" if parsed is not result else "text",
                "result": parsed,
                "result_chars": len(result),
            }
        jsonable = _to_jsonable(result)
        return {
            "result_type": "json",
            "result": jsonable,
            "result_chars": len(json.dumps(jsonable, ensure_ascii=False, default=str)),
        }

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


def tool_failure_handler(context: RunContextWrapper, error: Exception) -> str:
    """``failure_error_function`` that records the real exception before
    returning the SDK's default message to the model."""
    if _active_logger is not None:
        _active_logger.log_tool_error(context, error)
    return "An error occurred while running the tool. Please try again."
