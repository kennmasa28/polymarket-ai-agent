"""Flask application: pages, JSON API and Server-Sent Events."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import secrets
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import (
    Blueprint, Flask, Response, abort, current_app, jsonify, render_template, request,
    send_from_directory, stream_with_context,
)

from . import PROJECT_ROOT, auth, markets
from .agent_service import AgentService, ConflictError, find_log
from .auth import login_required
from .log_store import DEFAULT_LOG_DIR, build_session, list_log_files, read_events
from .serializers import session_json, summary_json

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__, url_prefix="/api")

_MEDIA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}/images/[A-Za-z0-9_.-]+\.(png|jpe?g|gif|webp)$")
_TOKEN_RE = re.compile(r"^\d{1,100}$")


# ------------------------------------------------------------------ helpers
@lru_cache(maxsize=256)
def _cached_session(path: str, mtime: float, size: int):
    return build_session(path, read_events(path))


def load_session(path: Path):
    stat = path.stat()
    return _cached_session(str(path), stat.st_mtime, stat.st_size)


def service() -> AgentService:
    return current_app.extensions["agent_service"]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json.loads(json.dumps(dataclasses.asdict(value), default=str))
    return json.loads(json.dumps(value, default=str))


def _error(message: str, status: int = 400):
    return jsonify(error=message), status


def _session_or_404(session_id: str):
    path = find_log(session_id)
    if path is None:
        abort(404)
    return load_session(path)


def _settings_from(body: dict[str, Any]) -> tuple[str | None, str | None]:
    model = (body.get("model") or "").strip() or None
    effort = body.get("reasoning_effort") or None
    if effort not in (None, "minimal", "low", "medium", "high"):
        effort = None
    if model and not re.match(r"^[A-Za-z0-9._:/-]{1,100}$", model):
        model = None
    return model, effort


# -------------------------------------------------------------------- pages
@pages.route("/")
@pages.route("/c/<conversation_id>")
@login_required
def chat(conversation_id: str | None = None):
    import config

    return render_template("chat.html", page="chat", conversation_id=conversation_id or "",
                           default_model=config.MODEL,
                           has_openai_key=bool(os.getenv("OPENAI_API_KEY")))


@pages.route("/trade")
@login_required
def trade():
    return render_template("trade.html", page="trade")


@pages.route("/logs")
@pages.route("/logs/<session_id>")
@login_required
def logs(session_id: str | None = None):
    return render_template("logs.html", page="logs", session_id=session_id or "")


@pages.route("/media/<path:filename>")
@login_required
def media(filename: str):
    if not _MEDIA_RE.match(filename):
        abort(404)
    return send_from_directory(DEFAULT_LOG_DIR, filename, max_age=3600)


# ------------------------------------------------------------ conversations
@api.get("/conversations")
@login_required
def conversations():
    items = []
    for path in list_log_files(DEFAULT_LOG_DIR):
        session = load_session(path)
        if session.meta.get("source") != "ui" or not session.turns:
            continue
        items.append(summary_json(session))
    return jsonify(items=items)


@api.get("/conversations/<conversation_id>")
@login_required
def conversation(conversation_id: str):
    session = _session_or_404(conversation_id)
    data = session_json(session)
    data["pending"] = service().pending(conversation_id)
    run = service().active_run(conversation_id)
    data["active_run"] = run.id if run else None
    return jsonify(data)


@api.post("/conversations")
@api.post("/conversations/<conversation_id>/messages")
@login_required
def send_message(conversation_id: str | None = None):
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return _error("メッセージが空です。")
    if len(text) > 8000:
        return _error("メッセージが長すぎます（8000文字まで）。")
    model, effort = _settings_from(body)
    try:
        run = service().send(conversation_id, text, model, effort)
    except KeyError:
        return _error("会話が見つかりません。", 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return jsonify(conversation_id=run.conversation_id, run_id=run.id), 202


@api.post("/conversations/<conversation_id>/approvals")
@login_required
def approvals(conversation_id: str):
    body = request.get_json(silent=True) or {}
    decisions = body.get("decisions")
    if not isinstance(decisions, dict):
        return _error("decisions が必要です。")
    try:
        run = service().resolve(conversation_id, decisions)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return jsonify(conversation_id=conversation_id, run_id=run.id), 202


@api.post("/conversations/<conversation_id>/close")
@login_required
def close_conversation(conversation_id: str):
    try:
        service().close(conversation_id)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return jsonify(ok=True)


@api.get("/runs/<run_id>/events")
@login_required
def run_events(run_id: str):
    run = service().get_run(run_id)
    if run is None:
        abort(404)
    start = request.args.get("from", type=int) or int(request.headers.get("Last-Event-ID", 0) or 0)

    @stream_with_context
    def stream():
        index = start
        yield "retry: 2000\n\n"
        while True:
            events, done = run.wait(index, timeout=15.0)
            if not events and not done:
                yield ": keep-alive\n\n"
                continue
            for event in events:
                index += 1
                payload = json.dumps(event, ensure_ascii=False, default=str)
                yield f"id: {index}\ndata: {payload}\n\n"
            if done and index >= len(run.events):
                return

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ trading data
@api.get("/portfolio")
@login_required
def portfolio():
    from trade import TRADE

    try:
        positions = TRADE().get_self_status()
    except Exception as exc:
        return _error(f"ポートフォリオを取得できませんでした: {exc}", 502)
    value = sum(p["size"] * p["price"] for p in positions)
    cost = sum(p["size"] * p["avr_price"] for p in positions)
    pnl = sum(p["delta"] for p in positions)
    return jsonify(positions=positions, totals={"value": value, "cost": cost, "pnl": pnl})


@api.get("/markets/trending")
@login_required
def trending():
    tag = request.args.get("tag") or None
    if tag and not re.match(r"^[a-z0-9-]{1,50}$", tag):
        return _error("tag の形式が正しくありません。")
    try:
        return jsonify(items=markets.trending_events(tag))
    except Exception as exc:
        return _error(f"イベントを取得できませんでした: {exc}", 502)


@api.get("/markets/event")
@login_required
def event():
    try:
        data = markets.event_by_slug(request.args.get("slug", ""))
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"イベントを取得できませんでした: {exc}", 502)
    if data is None:
        return _error("イベントが見つかりません。", 404)
    return jsonify(data)


@api.get("/markets/history")
@login_required
def history():
    token_id = request.args.get("token_id", "")
    if not _TOKEN_RE.match(token_id):
        return _error("token_id の形式が正しくありません。")
    try:
        return jsonify(points=markets.price_history(token_id, request.args.get("interval", "1w")))
    except Exception as exc:
        return _error(f"価格履歴を取得できませんでした: {exc}", 502)


@api.post("/orders")
@login_required
def place_order():
    """Manual live order from the trade page (the page asks for confirmation first)."""
    body = request.get_json(silent=True) or {}
    side = body.get("side")
    token_id = str(body.get("token_id", ""))
    if body.get("confirm") is not True:
        return _error("確認が必要です。")
    if side not in ("BUY", "SELL") or not _TOKEN_RE.match(token_id):
        return _error("注文内容が正しくありません。")
    try:
        quantity = float(body.get("amount_usd") if side == "BUY" else body.get("shares"))
    except (TypeError, ValueError):
        return _error("数量が正しくありません。")
    if not 0 < quantity <= 100_000:
        return _error("数量は0より大きい値を指定してください。")

    from trade import TRADE

    try:
        client = TRADE()
        if side == "BUY":
            response = client.make_buy_order(token_id, round(quantity, 2), "BUY")
        else:
            response = client.make_sell_order(token_id, round(quantity, 4), "SELL")
    except Exception as exc:
        return _error(f"注文に失敗しました: {type(exc).__name__}: {exc}", 502)
    return jsonify(ok=True, response=_jsonable(response))


# --------------------------------------------------------------------- logs
@api.get("/logs/sessions")
@login_required
def log_sessions():
    items = [summary_json(load_session(p)) for p in list_log_files(DEFAULT_LOG_DIR)]
    return jsonify(items=items)


@api.get("/logs/sessions/<session_id>")
@login_required
def log_session(session_id: str):
    return jsonify(session_json(_session_or_404(session_id)))


@api.get("/logs/sessions/<session_id>/events")
@login_required
def log_session_events(session_id: str):
    return jsonify(items=_session_or_404(session_id).events)


@api.get("/logs/sessions/<session_id>/download")
@login_required
def log_download(session_id: str):
    path = find_log(session_id)
    if path is None:
        abort(404)
    return send_from_directory(path.parent, path.name, as_attachment=True, mimetype="application/jsonl")


@api.get("/logs/tool-calls")
@login_required
def all_tool_calls():
    """Every tool call across sessions (for the overview's error list & tool chart)."""
    items = []
    for path in list_log_files(DEFAULT_LOG_DIR):
        session = load_session(path)
        for call in session.tools:
            items.append({
                "session_id": session.session_id, "name": call.name, "status": call.status,
                "start_ts": call.start_ts, "duration_ms": call.duration_ms,
                "error": (call.error or {}).get("error"), "error_type": (call.error or {}).get("error_type"),
            })
    return jsonify(items=items)


# ---------------------------------------------------------------------- app
def _secret_key(instance_path: Path) -> str:
    key = os.getenv("FLASK_SECRET_KEY")
    if key:
        return key
    path = instance_path / "secret_key"
    if path.exists():
        return path.read_text().strip()
    instance_path.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    path.write_text(key)
    path.chmod(0o600)
    return key


def create_app(agent_service: AgentService | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(PROJECT_ROOT / "instance"))
    app.config.update(
        SECRET_KEY=_secret_key(Path(app.instance_path)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("POLYAGENT_SECURE_COOKIE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        JSON_AS_ASCII=False,
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    )
    app.json.ensure_ascii = False
    app.extensions["agent_service"] = agent_service or AgentService()
    app.jinja_env.globals["csrf_token"] = auth.csrf_token
    app.register_blueprint(auth.bp)
    app.register_blueprint(pages)
    app.register_blueprint(api)

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        return response

    @app.errorhandler(400)
    @app.errorhandler(404)
    def json_errors(error):
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(error, "description", str(error))), error.code
        return error

    return app
