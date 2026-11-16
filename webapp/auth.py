"""Single-user login for the web app.

Credentials come only from environment variables; both are required:

    POLYAGENT_USERNAME
    POLYAGENT_PASSWORD_HASH  generate with:  python -m webapp.passwords 'password'

Hashes made by werkzeug (``scrypt:...`` / ``pbkdf2:...``) are verified
directly.  Other formats are handed to ``viewer/password_hash.py``'s
``verify_password`` when that local (git-ignored) helper exists.
"""

from __future__ import annotations

import hmac
import importlib.util
import os
import secrets
import time
from functools import wraps
from typing import Callable
from urllib.parse import urlparse

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash

from . import PROJECT_ROOT

bp = Blueprint("auth", __name__)

CREDENTIAL_VARS = ("POLYAGENT_USERNAME", "POLYAGENT_PASSWORD_HASH")
LEGACY_HASHER = PROJECT_ROOT / "viewer" / "password_hash.py"


def credentials() -> tuple[str, str]:
    return os.getenv("POLYAGENT_USERNAME", ""), os.getenv("POLYAGENT_PASSWORD_HASH", "")


def missing_credentials() -> list[str]:
    """Names of the required environment variables that are not set."""
    return [name for name in CREDENTIAL_VARS if not os.getenv(name)]


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(stored_hash, password)
    if LEGACY_HASHER.exists():
        spec = importlib.util.spec_from_file_location("polyagent_legacy_password_hash", LEGACY_HASHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return bool(module.verify_password(password, stored_hash))
    return False


def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = session["csrf"] = secrets.token_urlsafe(32)
    return token


def check_csrf() -> None:
    """Reject state-changing requests that do not carry the session's token."""
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    if not hmac.compare_digest(sent, session.get("csrf", "")) or not sent:
        abort(400, description="CSRF token missing or invalid")


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/") or request.path.startswith("/media/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            check_csrf()
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target: str | None) -> str:
    if not target:
        return url_for("pages.chat")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for("pages.chat")
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    username, password_hash = credentials()
    missing = missing_credentials()
    error = None
    if request.method == "POST" and not missing:
        check_csrf()
        valid_user = hmac.compare_digest(request.form.get("username", ""), username)
        valid_password = verify_password(request.form.get("password", ""), password_hash)
        if valid_user and valid_password:
            session.clear()
            session.permanent = True
            session["user"] = username
            csrf_token()
            return redirect(_safe_next(request.args.get("next")))
        time.sleep(1.0)  # slow down guessing
        error = "ユーザー名またはパスワードが正しくありません。"
    return render_template("login.html", error=error, missing=missing)


@bp.route("/logout", methods=["POST"])
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))
