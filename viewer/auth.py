"""Shared authentication gate for every Streamlit viewer page."""

from __future__ import annotations

import hmac
import os
from typing import Any

import streamlit as st

from password_hash import verify_password


def _secret_auth() -> dict[str, Any]:
    """Return the optional ``[auth]`` section without requiring a secrets file."""
    try:
        auth = st.secrets.get("auth", {})
    except Exception:
        # Streamlit raises a version-specific exception when no secrets file
        # exists. Environment-variable authentication must still work then.
        return {}
    return dict(auth) if auth else {}


def _credentials() -> tuple[str, str]:
    auth = _secret_auth()
    username = os.getenv("POLYAGENT_USERNAME") or auth.get("username") or "admin"
    password_hash = os.getenv("POLYAGENT_PASSWORD_HASH") or auth.get("password_hash") or ""
    return str(username), str(password_hash)


def _logout() -> None:
    chat = st.session_state.get("pa_chat")
    if chat is not None:
        try:
            chat.close()
        except Exception:
            pass
    for key in list(st.session_state):
        del st.session_state[key]


def require_auth() -> None:
    """Stop page rendering until the configured credentials are supplied."""
    if st.session_state.get("pa_authenticated") is True:
        with st.sidebar:
            st.button("ログアウト", on_click=_logout, width="stretch")
        return

    expected_username, expected_password_hash = _credentials()

    st.markdown("## 🔐 PolyAgent ログイン")
    if not expected_password_hash:
        st.error("ログイン用のパスワードハッシュが設定されていません。")
        st.caption(
            "環境変数 `POLYAGENT_PASSWORD_HASH`、または "
            "`.streamlit/secrets.toml` の `[auth] password_hash` を設定してください。"
        )
        st.stop()

    with st.form("pa_login_form"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン", type="primary", width="stretch")

    if submitted:
        valid_username = hmac.compare_digest(username, expected_username)
        valid_password = verify_password(password, expected_password_hash)
        if valid_username and valid_password:
            st.session_state["pa_authenticated"] = True
            st.rerun()
        st.error("ユーザー名またはパスワードが正しくありません。")

    st.stop()
