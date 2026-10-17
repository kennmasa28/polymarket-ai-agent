"""PolyAgent: chat with the Polymarket trading agent and approve its orders.

Run with:  streamlit run viewer/view_app.py

Every conversation is logged by ``src/agent_logger.py``; the log is also the
source this page renders the chat from, so past conversations can be reopened
and analysed in detail on the "logview" page.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

VIEWER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(VIEWER_DIR))
sys.path.insert(0, str(VIEWER_DIR.parent / "src"))

from auth import require_auth  # noqa: E402

st.set_page_config(page_title="PolyAgent", page_icon="🤖", layout="wide")
require_auth()

from log_store import (  # noqa: E402
    DEFAULT_LOG_DIR,
    DEFAULT_PRICES,
    Session,
    ToolCall,
    Turn,
    build_session,
    cost_usd,
    list_log_files,
    read_events,
)

try:
    import config
    from agent_runner import TradingChat
    from trade import TRADE
except Exception as exc:  # missing dependency / credentials
    st.error(f"エージェントを読み込めませんでした: {exc}")
    st.stop()

ORDER_TOOLS = {"buy_token", "sell_token"}
NEW = "__new__"
EFFORTS = ["(既定)", "minimal", "low", "medium", "high"]
QUICK_ACTIONS = [
    ("📋", "ポートフォリオ確認", "現在のポートフォリオを確認して、ポジションごとの損益を表にまとめて"),
    ("🔥", "注目マーケット", "直近24時間で取引量の多い注目イベントを教えて"),
    ("🤖", "AI関連を探す", "AI関連で取引量の多いマーケットを探して、価格推移も見せて"),
    ("🛡️", "リスク評価", "保有ポジションのリスクを評価して、気になる点を教えて"),
]

CSS = """
<style>
.block-container {padding-top: 3rem; padding-bottom: 6rem;}
.pa-hero {display:flex; align-items:center; gap:.7rem; margin-bottom:.1rem;}
.pa-hero h1 {font-size:1.45rem; margin:0; padding:0;}
.pa-sub {opacity:.65; font-size:.84rem; margin-bottom:.8rem;}
.pa-chip {display:inline-block; padding:.05rem .5rem; margin:0 .25rem .2rem 0; border-radius:999px;
          font-size:.74rem; line-height:1.3rem; background:rgba(127,127,127,.14); white-space:nowrap;}
.pa-chip.ok {background:rgba(16,185,129,.18); color:#10b981;}
.pa-chip.error {background:rgba(239,68,68,.18); color:#ef4444;}
.pa-chip.warn {background:rgba(245,158,11,.20); color:#d97706;}
.pa-chip.violet {background:rgba(139,92,246,.18); color:#8b5cf6;}
.pa-chip.blue {background:rgba(59,130,246,.18); color:#3b82f6;}
.pa-reason {border-left:3px solid #8b5cf6; padding:.1rem 0 .1rem .7rem; margin:.3rem 0 .5rem;
            font-size:.86rem; opacity:.9;}
.pa-step {font-size:.72rem; font-weight:700; letter-spacing:.05em; opacity:.6; margin-top:.4rem;}
.pa-order {font-size:1.05rem; font-weight:700;}
.pa-side-BUY {color:#10b981;} .pa-side-SELL {color:#ef4444;}
div[class*="st-key-approval"] {border:2px solid #f59e0b !important; background:rgba(245,158,11,.08);}
div[class*="st-key-order-ok"] {border-left:4px solid #10b981 !important; background:rgba(16,185,129,.06);}
div[class*="st-key-order-ng"] {border-left:4px solid #ef4444 !important; background:rgba(239,68,68,.06);}
div[class*="st-key-order-rejected"] {border-left:4px solid #94a3b8 !important; background:rgba(148,163,184,.08);}
div[class*="st-key-panel"] div[data-testid="stMetricValue"] {font-size:1.25rem;}
</style>
"""


# --------------------------------------------------------------------- helpers
def chip(text: str, cls: str = "") -> str:
    return f'<span class="pa-chip {cls}">{html.escape(str(text))}</span>'


def fmt_ms(ms: int | float | None) -> str:
    if ms is None:
        return "–"
    return f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def reasoning_html(text: str) -> str:
    """Reasoning summaries are Markdown; keep their bold headings inside HTML."""
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped).replace("\n", "<br>")


def short(value: Any, limit: int = 80) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_value(value: Any) -> None:
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        st.dataframe(pd.DataFrame([{k: short(v, 200) if isinstance(v, (dict, list)) else v
                                    for k, v in row.items()} for row in value]), hide_index=True)
    elif isinstance(value, (dict, list)):
        st.json(value, expanded=2)
    elif value is None:
        st.caption("(なし)")
    else:
        st.code(str(value), language=None, wrap_lines=True)


def order_side(tool: str) -> str:
    return "BUY" if tool == "buy_token" else "SELL"


def order_amount(tool: str, args: dict[str, Any]) -> str:
    if tool == "buy_token":
        return f"{args.get('amount_usd', '?')} USDC"
    return f"{args.get('shares', '?')} shares"


def order_outcome(call: ToolCall) -> tuple[str, str]:
    """(css key suffix, label) describing what happened to an order."""
    if call.approval == "rejected":
        return "rejected", "⛔ 却下（未発注）"
    if call.approval == "pending":
        return "rejected", "⏸ 承認待ち"
    if call.error:
        return "ng", f"✗ エラー: {call.error.get('error')}"
    result = call.result if isinstance(call.result, dict) else {}
    if result.get("success") is False or result.get("errorMsg"):
        return "ng", f"✗ 不成立: {result.get('errorMsg') or '失敗'}"
    if call.end_ts is None:
        return "rejected", "… 実行中"
    return "ok", "✅ 注文送信済み"


# ------------------------------------------------------------- conversations
@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float, size: int) -> Session:
    return build_session(path, read_events(path))


def load_session(path: Path | str) -> Session | None:
    path = Path(path)
    if not path.exists():
        return None
    stat = path.stat()
    return _load(str(path), stat.st_mtime, stat.st_size)


def ui_conversations() -> dict[str, str]:
    """Past chats started from this UI: {log path: label}."""
    convs = {}
    for path in list_log_files(DEFAULT_LOG_DIR):
        session = load_session(path)
        if session is None or session.meta.get("source") != "ui" or not session.turns:
            continue
        first = next((t.user_text for t in session.turns if t.user_text), "")
        start = session.start.strftime("%m/%d %H:%M") if session.start else path.stem
        convs[str(path)] = f"{start} · {first[:22]}"
    return convs


def current_chat() -> TradingChat | None:
    """The open chat if it belongs to the selected conversation, else close it."""
    chat = st.session_state.get("pa_chat")
    if chat is None:
        return None
    conv = st.session_state.get("pa_conv", NEW)
    if conv == NEW and st.session_state.get("pa_chat_is_new") or str(chat.log_path) == conv:
        return chat
    chat.close()
    st.session_state["pa_chat"] = None
    return None


def ensure_chat() -> TradingChat:
    """Open (or resume) the selected conversation for sending a message."""
    chat = current_chat()
    model = st.session_state.get("pa_model") or config.MODEL
    effort = st.session_state.get("pa_effort", EFFORTS[0])
    effort = None if effort == EFFORTS[0] else effort
    if chat is None:
        conv = st.session_state.get("pa_conv", NEW)
        chat = TradingChat(source="ui", log_path=None if conv == NEW else conv,
                           model=model, reasoning_effort=effort)
        st.session_state["pa_chat"] = chat
        st.session_state["pa_chat_is_new"] = conv == NEW
    else:
        chat.configure(model, effort)
    return chat


def new_conversation() -> None:
    chat = st.session_state.get("pa_chat")
    if chat is not None:
        chat.close()
    st.session_state["pa_chat"] = None
    st.session_state["pa_conv"] = NEW


def open_in_logview(path: str) -> None:
    st.session_state["session"] = path
    st.session_state["mode"] = "🔍 詳細"
    st.session_state["date"] = "すべて"
    st.session_state["pa_goto_logview"] = True


# -------------------------------------------------------------------- sidebar
def sidebar() -> None:
    with st.sidebar:
        st.latex(r'''\rm{PolyAgent}''')
        st.button("＋ 新しい会話", on_click=new_conversation, type="primary", width="stretch")

        convs = ui_conversations()
        chat = st.session_state.get("pa_chat")
        if chat is not None and st.session_state.get("pa_conv") == NEW and str(chat.log_path) in convs:
            # The new chat has been written to disk: select it in the history.
            st.session_state["pa_conv"] = str(chat.log_path)
            st.session_state["pa_chat_is_new"] = False
        options = [NEW] + list(convs)
        if st.session_state.get("pa_conv") not in options:
            st.session_state["pa_conv"] = NEW
        st.selectbox("会話履歴", options, key="pa_conv",
                     format_func=lambda p: "🆕 新しい会話" if p == NEW else convs.get(p, p))

        st.divider()
        model_list = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
        st.selectbox("モデル", options=model_list, key="pa_model")
        st.selectbox("reasoning effort", EFFORTS, key="pa_effort")
        st.caption("🛡️ 売買はエージェントが提案した注文を **あなたが承認したときだけ** 実行されます。")
        if not os.getenv("OPENAI_API_KEY"):
            st.warning("OPENAI_API_KEY が設定されていません。")


# ------------------------------------------------------------- chat rendering
def render_activity(turn: Turn, session: Session) -> None:
    """Reasoning and tool calls of one turn, collapsed by default."""
    tools = turn.tools
    if not turn.steps:
        return
    label = (f"🧠 思考とツール　·　{len(turn.steps)} steps · {len(tools)} tools"
             + (f" · {fmt_ms(turn.duration_ms)}" if turn.duration_ms else ""))
    with st.expander(label):
        for step in turn.steps:
            st.markdown(f'<div class="pa-step">STEP {step.step} · LLM {fmt_ms(step.duration_ms)}</div>',
                        unsafe_allow_html=True)
            for text in step.reasoning:
                st.markdown(f'<div class="pa-reason">{reasoning_html(text)}</div>', unsafe_allow_html=True)
            if step.tools:
                cols = st.columns(min(len(step.tools), 3))
                for i, call in enumerate(step.tools):
                    icon = {"ok": "✓", "error": "✗", "rejected": "⛔", "awaiting": "⏸"}.get(call.status, "…")
                    label = f"{icon} {call.name} · {fmt_ms(call.duration_ms)}"
                    with cols[i % len(cols)].popover(label, width="stretch"):
                        st.caption("引数")
                        st.json(call.arguments or {}, expanded=True)
                        st.caption("返り値")
                        if call.approval == "rejected":
                            st.info("ユーザーが却下しました")
                        elif call.error:
                            st.error(f"{call.error.get('error_type')}: {call.error.get('error')}")
                        else:
                            image = session.image_file(call)
                            if image is not None and image.exists():
                                st.image(str(image))
                            else:
                                render_value(call.result)


def render_order_card(call: ToolCall, key: str) -> None:
    kind, label = order_outcome(call)
    args = call.arguments if isinstance(call.arguments, dict) else {}
    side = order_side(call.name)
    with st.container(border=True, key=f"order-{kind}-{key}"):
        st.markdown(
            f'<span class="pa-order pa-side-{side}">{side}</span> '
            f'{chip("token " + str(args.get("token_id", "?")))}{chip(order_amount(call.name, args), "blue")} '
            f"{html.escape(label)}",
            unsafe_allow_html=True,
        )


def render_turn(turn: Turn, session: Session) -> None:
    with st.chat_message("user"):
        st.markdown(turn.user_text)
    with st.chat_message("assistant"):
        render_activity(turn, session)
        messages = [m for s in turn.steps for m in s.messages if m]
        for text in messages:
            st.markdown(text)
        for call in turn.tools:
            image = session.image_file(call)
            if image is not None and image.exists():
                st.image(str(image), caption=f"{call.name}({short(call.arguments, 50)})")
        for call in turn.tools:
            if call.name in ORDER_TOOLS:
                render_order_card(call, f"{turn.turn}-{call.call_id}")
        if turn.error:
            st.error(f"エラー: {turn.error.get('error_type')}: {turn.error.get('error')}")
        elif not messages and turn.status == "running":
            st.caption("（応答が記録されていません）")


def render_approvals(chat: TradingChat) -> None:
    """Approval cards for orders the agent wants to place."""
    with st.chat_message("assistant", avatar="⚠️"):
        st.markdown("**注文の承認が必要です。** 内容を確認して、発注するか却下してください。")
        decisions = st.session_state.setdefault("pa_decisions", {})
        for order in chat.pending:
            side = order_side(order.tool)
            with st.container(border=True, key=f"approval-{order.call_id}"):
                c1, c2, c3 = st.columns([1, 2, 1.4])
                c1.markdown(f'<div class="pa-order pa-side-{side}" style="font-size:1.6rem">{side}</div>',
                            unsafe_allow_html=True)
                c2.markdown(f"**token** `{order.arguments.get('token_id', '?')}`")
                c3.metric("数量" if side == "SELL" else "金額", order_amount(order.tool, order.arguments))
                position = next((p for p in st.session_state.get("pa_portfolio", {}).get("data", []) or []
                                 if str(p.get("token_id")) == str(order.arguments.get("token_id"))), None)
                if position:
                    c2.caption(f"保有中: {position_title(position)} · {position['size']:.2f} shares "
                               f"@ 平均 {position['avr_price']:.3f} / 現在 {position['price']:.3f}")
                st.caption("⚠️ FAK 成行注文です。板の状況により一部のみ約定・価格が変動する可能性があります。")
                note = st.text_input("却下理由（任意・エージェントに伝えます）", key=f"pa_note_{order.call_id}")
                b1, b2 = st.columns(2)
                if b1.button("✅ 承認して発注", key=f"pa_ok_{order.call_id}", type="primary",
                             width="stretch"):
                    decisions[order.call_id] = (True, None)
                if b2.button("❌ 却下", key=f"pa_ng_{order.call_id}", width="stretch"):
                    decisions[order.call_id] = (False, note)
                if order.call_id in decisions:
                    st.caption("✅ 承認済み" if decisions[order.call_id][0] else "⛔ 却下済み")
        if chat.pending and all(o.call_id in decisions for o in chat.pending):
            st.session_state["pa_resolve"] = {
                cid: decisions[cid] for cid in (o.call_id for o in chat.pending)
            }
            st.session_state["pa_decisions"] = {}


# ----------------------------------------------------------------- live run
class LiveStatus:
    """Shows the agent's progress inside an ``st.status`` while it runs."""

    def __init__(self, label: str):
        self.box = st.status(label, expanded=True)
        self.order_done = False

    def __call__(self, record: dict[str, Any]) -> None:
        event = record.get("event")
        with self.box:
            if event == "llm_start":
                self.box.update(label=f"🧠 考えています…（step {record.get('step')}）")
            elif event == "llm_end":
                for out in record.get("outputs", []):
                    if out.get("type") == "reasoning":
                        for text in out.get("summary", []):
                            st.markdown(f'<div class="pa-reason">{reasoning_html(short(text, 400))}</div>',
                                        unsafe_allow_html=True)
                    elif out.get("type") == "function_call":
                        st.markdown(f"🔧 `{out.get('name')}` {short(out.get('arguments'), 70)}")
            elif event == "tool_start":
                self.box.update(label=f"🔧 {record.get('tool')} を実行中…")
            elif event == "tool_end":
                st.markdown(f"&nbsp;&nbsp;↳ ✓ `{record.get('tool')}` 完了（{fmt_ms(record.get('duration_ms'))}）")
                if record.get("tool") in ORDER_TOOLS:
                    self.order_done = True
            elif event == "tool_error":
                st.markdown(f"&nbsp;&nbsp;↳ ✗ `{record.get('tool')}` エラー: {short(record.get('error'), 100)}")
            elif event == "approval_request":
                st.markdown(f"⏸ `{record.get('tool')}` の承認を待っています")

    def finish(self, label: str, state: str = "complete") -> None:
        self.box.update(label=label, state=state, expanded=False)


def run_agent(prompt: str | None = None, resolve: dict[str, tuple[bool, str | None]] | None = None) -> None:
    chat = ensure_chat()
    if prompt is not None:
        with st.chat_message("user"):
            st.markdown(prompt)
    with st.chat_message("assistant"):
        live = LiveStatus("🤖 エージェントが作業中…" if prompt else "📨 注文の判断を伝えています…")
        chat.set_listener(live)
        try:
            if prompt is not None:
                result = chat.send(prompt)
            else:
                result = chat.resolve({k: v[0] for k, v in resolve.items()},
                                      {k: v[1] for k, v in resolve.items() if v[1]})
        finally:
            chat.set_listener(None)
        if result.error is not None:
            live.finish("エラーが発生しました", state="error")
        elif result.needs_approval:
            live.finish("⏸ 注文の承認待ち")
        else:
            live.finish("✓ 完了")
    if live.order_done:
        st.session_state.pop("pa_portfolio", None)  # refresh positions after an order
    st.rerun()


# ------------------------------------------------------------------ side panels
def position_title(position: dict[str, Any]) -> str:
    first = (position.get("text") or "").splitlines()[:1]
    return first[0].replace("タイトル:", "").strip() if first else str(position.get("condition_id", ""))


def load_portfolio(force: bool = False) -> dict[str, Any]:
    cached = st.session_state.get("pa_portfolio")
    if cached is not None and not force:
        return cached
    try:
        data = TRADE().get_self_status()
        cached = {"data": data, "error": None, "at": time.strftime("%H:%M:%S")}
    except Exception as exc:
        cached = {"data": [], "error": str(exc), "at": time.strftime("%H:%M:%S")}
    st.session_state["pa_portfolio"] = cached
    return cached


def render_portfolio() -> None:
    with st.container(border=True, key="panel-portfolio"):
        head, btn = st.columns([5, 1], vertical_alignment="center")
        head.markdown("##### 💼 ポートフォリオ")
        force = btn.button("🔄", help="最新の保有状況を取得", key="pa_refresh")
        with st.spinner("取得中…"):
            pf = load_portfolio(force)
        if pf["error"]:
            st.warning(f"取得できませんでした: {pf['error']}")
            return
        data = pf["data"] or []
        value = sum(p["size"] * p["price"] for p in data)
        pnl = sum(p.get("delta", 0) for p in data)
        m1, m2, m3 = st.columns(3)
        m1.metric("評価額", f"${value:,.2f}")
        m2.metric("含み損益", f"${pnl:+,.2f}")
        m3.metric("銘柄数", len(data))
        if data:
            df = pd.DataFrame([{
                "市場": f"{position_title(p)} ({p.get('token_name')})", "数量": p["size"],
                "平均": p["avr_price"], "現在": p["price"], "損益": p.get("delta", 0),
            } for p in data])
            st.dataframe(df, hide_index=True, column_config={
                "数量": st.column_config.NumberColumn(format="%.2f"),
                "平均": st.column_config.NumberColumn(format="%.3f"),
                "現在": st.column_config.NumberColumn(format="%.3f"),
                "損益": st.column_config.NumberColumn(format="%+.2f"),
            })
        st.caption(f"更新 {pf['at']}")


def render_quick_actions(disabled: bool) -> None:
    with st.container(border=True, key="panel-quick"):
        st.markdown("##### ⚡ クイックアクション")
        cols = st.columns(2)
        for i, (icon, label, prompt) in enumerate(QUICK_ACTIONS):
            if cols[i % 2].button(f"{icon} {label}", key=f"pa_quick_{i}", disabled=disabled,
                                  width="stretch", help=prompt):
                st.session_state["pa_queued"] = prompt


def render_session_panel(session: Session | None) -> None:
    with st.container(border=True, key="panel-session"):
        st.markdown("##### 🧾 この会話")
        if session is None:
            st.caption("まだメッセージがありません。")
            return
        orders = [c for c in session.tools if c.name in ORDER_TOOLS]
        tokens = sum(s.usage.get("total_tokens", 0) for s in session.steps)
        cost = sum(cost_usd(s.usage, DEFAULT_PRICES) for s in session.steps)
        m1, m2, m3 = st.columns(3)
        m1.metric("ターン", len(session.turns))
        m2.metric("ツール", len(session.tools))
        m3.metric("コスト", f"${cost:.3f}", help=f"{tokens:,} tokens（料金はログビューアで調整可）")
        if orders:
            st.markdown("**注文履歴**")
            for call in reversed(orders):
                render_order_card(call, f"side-{call.call_id}")
        st.button("📊 ログビューアで詳しく見る", on_click=open_in_logview, args=(str(session.path),),
                  width="stretch")


# ------------------------------------------------------------------------ main
def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if st.session_state.pop("pa_goto_logview", False):
        st.switch_page("pages/3_logview.py")
    sidebar()

    chat = current_chat()
    conv = st.session_state.get("pa_conv", NEW)
    log_path = chat.log_path if chat is not None else (None if conv == NEW else Path(conv))
    session = load_session(log_path) if log_path is not None else None
    if session is not None and not session.turns:
        session = None
    pending = bool(chat and chat.pending)

    left, right = st.columns([2.3, 1], gap="large")
    with left:
        title = short(session.turns[0].user_text, 30) if session else "新しい会話"
        st.markdown(f'<div class="pa-hero"><h1>🤖 {html.escape(title)}</h1></div>'
                    f'<div class="pa-sub">model <code>{html.escape(st.session_state.get("pa_model") or config.MODEL)}'
                    f"</code> · Polymarket トレーディングエージェント</div>", unsafe_allow_html=True)
        if session is not None:
            for turn in session.turns:
                render_turn(turn, session)
        if pending:
            render_approvals(chat)

    with right:
        render_portfolio()
        render_quick_actions(disabled=pending)
        render_session_panel(session)

    prompt = st.chat_input(
        "承認待ちの注文があります" if pending else "メッセージを入力（Enterで送信）", disabled=pending)
    queued = st.session_state.pop("pa_queued", None)
    resolve = st.session_state.pop("pa_resolve", None)
    with left:
        if resolve and chat is not None and chat.pending:
            run_agent(resolve=resolve)
        elif (prompt or queued) and not pending:
            run_agent(prompt=prompt or queued)


main()
