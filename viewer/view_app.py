"""PolyViewer: analyse the agent's step-by-step logs.

Run with:  streamlit run viewer/view_app.py
Logs are written by ``src/agent_logger.py`` to ``agent_logs/<date>/<session>.jsonl``.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from log_store import (
    DEFAULT_LOG_DIR,
    DEFAULT_PRICES,
    Session,
    ToolCall,
    build_session,
    cost_usd,
    list_log_files,
    parse_ts,
    read_events,
    session_summary,
)

st.set_page_config(page_title="PolyViewer", page_icon="🛰️", layout="wide")

# Colour per element kind; also used by charts so the legend matches the cards.
COLORS = {
    "user": "#f59e0b",
    "reasoning": "#8b5cf6",
    "tool": "#3b82f6",
    "ok": "#10b981",
    "error": "#ef4444",
    "message": "#64748b",
    "llm": "#8b5cf6",
}

CSS = """
<style>
.block-container {padding-top: 3.2rem;}
.pv-hero {display:flex; align-items:center; gap:.8rem; margin-bottom:.3rem;}
.pv-hero h1 {font-size:1.7rem; margin:0; padding:0;}
.pv-sub {opacity:.65; font-size:.85rem; margin-bottom:1rem;}
.pv-chip {display:inline-block; padding:.08rem .55rem; margin:0 .25rem .2rem 0; border-radius:999px;
          font-size:.76rem; line-height:1.35rem; background:rgba(127,127,127,.14); white-space:nowrap;}
.pv-chip.ok {background:rgba(16,185,129,.18); color:#10b981;}
.pv-chip.error {background:rgba(239,68,68,.18); color:#ef4444;}
.pv-chip.running {background:rgba(245,158,11,.18); color:#d97706;}
.pv-chip.violet {background:rgba(139,92,246,.18); color:#8b5cf6;}
.pv-chip.blue {background:rgba(59,130,246,.18); color:#3b82f6;}
.pv-label {font-weight:700; font-size:.82rem; letter-spacing:.04em; text-transform:uppercase; margin-right:.5rem;}
.pv-turn {margin:1.6rem 0 .6rem; padding:.55rem .9rem; border-radius:.6rem;
          background:linear-gradient(90deg, rgba(245,158,11,.20), rgba(245,158,11,0));
          border-left:5px solid #f59e0b;}
.pv-turn b {font-size:1.05rem; margin-right:.6rem;}
.pv-step {margin:.9rem 0 .35rem; font-size:.78rem; opacity:.8; display:flex; align-items:center; gap:.5rem;}
.pv-step:after {content:""; flex:1; height:1px; background:rgba(127,127,127,.3);}
.pv-mono {font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:.78rem; opacity:.75;}
div[class*="st-key-card-reason"] {border-left:4px solid #8b5cf6 !important; background:rgba(139,92,246,.06);}
div[class*="st-key-card-tool-ok"] {border-left:4px solid #3b82f6 !important; background:rgba(59,130,246,.05);}
div[class*="st-key-card-tool-error"] {border-left:4px solid #ef4444 !important; background:rgba(239,68,68,.06);}
div[class*="st-key-card-tool-running"] {border-left:4px solid #f59e0b !important; background:rgba(245,158,11,.06);}
div[class*="st-key-card-msg"] {border-left:4px solid #64748b !important; background:rgba(100,116,139,.06);}
div[class*="st-key-card-err"] {border-left:4px solid #ef4444 !important; background:rgba(239,68,68,.08);}
div[class*="st-key-kpi"] div[data-testid="stMetric"] {background:rgba(127,127,127,.07); border-radius:.6rem; padding:.5rem .8rem;}
div[class*="st-key-kpi"] div[data-testid="stMetricValue"] {font-size:1.45rem;}
div[class*="st-key-kpi"] div[data-testid="stMetricLabel"] p {font-size:.78rem;}
.pv-name {font-weight:700; font-size:.92rem; margin-right:.5rem; font-family:ui-monospace, SFMono-Regular, Menlo, monospace;}
</style>
"""


# --------------------------------------------------------------------------- utils
def fmt_ms(ms: int | float | None) -> str:
    if ms is None:
        return "–"
    return f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def fmt_int(n: int | float | None) -> str:
    return "–" if n is None else f"{int(n):,}"


def fmt_time(ts: str | None) -> str:
    dt = parse_ts(ts)
    return dt.strftime("%H:%M:%S") if dt else "–"


def chip(text: str, cls: str = "") -> str:
    return f'<span class="pv-chip {cls}">{html.escape(str(text))}</span>'


def status_chip(status: str) -> str:
    return {
        "ok": chip("✓ OK", "ok"),
        "error": chip("✗ ERROR", "error"),
        "running": chip("… 実行中", "running"),
    }[status]


def usage_chips(usage: dict[str, Any], prices: tuple[float, float, float]) -> str:
    if not usage:
        return ""
    return (
        chip(f"in {fmt_int(usage.get('input_tokens'))} (cache {fmt_int(usage.get('cached_tokens'))})")
        + chip(f"out {fmt_int(usage.get('output_tokens'))} (reason {fmt_int(usage.get('reasoning_tokens'))})", "violet")
        + chip(f"${cost_usd(usage, prices):.4f}")
    )


def compact_json(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


def highlight(text: str, query: str) -> str:
    if not query:
        return text
    return re.sub(f"({re.escape(query)})", r":orange-background[\1]", text, flags=re.IGNORECASE)


def to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """DataFrame where nested values are shown as JSON strings."""
    def cell(v: Any) -> Any:
        return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    return pd.DataFrame([{k: cell(v) for k, v in r.items()} for r in rows])


def render_value(value: Any, key: str) -> None:
    """Render a tool argument / result in the most readable form."""
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        tab_table, tab_json = st.tabs([f"📋 表 ({len(value)}行)", "{ } JSON"])
        with tab_table:
            st.dataframe(to_frame(value), hide_index=True, key=f"df-{key}")
        with tab_json:
            st.json(value, expanded=1)
    elif isinstance(value, (dict, list)):
        st.json(value, expanded=2)
    elif value is None:
        st.caption("(なし)")
    else:
        text = str(value)
        if len(text) > 400 or "\n" in text:
            st.code(text, language=None, wrap_lines=True)
        else:
            st.markdown(f"`{text}`" if text else "(空文字)")


def render_tool_result(session: Session, call: ToolCall, key: str) -> None:
    if call.error:
        st.error(f"**{call.error.get('error_type')}**: {call.error.get('error')}")
        with st.popover("Traceback"):
            st.code(call.error.get("traceback") or "", language="python")
        st.caption("モデルに返された値:")
    image = session.image_file(call)
    if image is not None:
        if image.exists():
            st.image(str(image), caption=image.name)
        else:
            st.warning(f"画像ファイルが見つかりません: {image}")
    elif call.image_url:
        st.image(call.image_url)
    else:
        render_value(call.result, key)


# ---------------------------------------------------------------------- loading
@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float, size: int) -> Session:
    return build_session(path, read_events(path))


def load_session(path: Path) -> Session:
    stat = path.stat()
    return _load(str(path), stat.st_mtime, stat.st_size)


# ---------------------------------------------------------------------- sidebar
def sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.markdown("## 🛰️ PolyViewer")
        log_dir = Path(st.text_input("ログディレクトリ", value=str(DEFAULT_LOG_DIR)))
        files = list_log_files(log_dir)

        st.session_state.setdefault("mode", "🔍 詳細")
        if "open_session" in st.session_state:  # row clicked in the overview table
            st.session_state["session"] = st.session_state.pop("open_session")
            st.session_state["mode"] = "🔍 詳細"
            st.session_state["date"] = "すべて"
        mode = st.segmented_control(
            "表示モード", ["🔍 詳細", "🌐 全体"], key="mode", required=True,
        )
        dates = sorted({p.parent.name for p in files}, reverse=True)
        date = st.selectbox("日付", ["すべて"] + dates, key="date")
        if date != "すべて":
            files = [p for p in files if p.parent.name == date]

        session_path = None
        if mode == "🔍 詳細" and files:
            labels = {}
            for p in files:
                s = load_session(p)
                first = next((t.user_text for t in s.turns if t.user_text), "")
                live = "🟢" if not s.ended else "⚪"
                start = s.start.strftime("%m/%d %H:%M:%S") if s.start else p.stem
                labels[str(p)] = f"{live} {start} · {len(s.turns)}T · {first[:18]}"
            if st.session_state.get("session") not in labels:
                st.session_state["session"] = str(files[0])
            session_path = Path(st.selectbox(
                "セッション", list(labels), format_func=labels.get, key="session",
            ))

        with st.expander("💲 料金設定 (USD / 1M tokens)"):
            p_in = st.number_input("入力", value=DEFAULT_PRICES[0], min_value=0.0, step=0.05, format="%.3f")
            p_cache = st.number_input("キャッシュ入力", value=DEFAULT_PRICES[1], min_value=0.0, step=0.01, format="%.3f")
            p_out = st.number_input("出力", value=DEFAULT_PRICES[2], min_value=0.0, step=0.1, format="%.3f")
            st.caption("コストは推定値です。使用モデルの料金に合わせて調整してください。")

        live = st.toggle("🔄 ライブ更新", help="実行中のセッションを数秒ごとに再読み込みします")
        interval = st.slider("更新間隔(秒)", 2, 30, 5, disabled=not live)
        st.caption(f"{len(files)} セッション / `{log_dir}`")

    return {
        "log_dir": log_dir, "files": files, "mode": mode, "session_path": session_path,
        "prices": (p_in, p_cache, p_out), "live": live, "interval": interval,
    }


# ---------------------------------------------------------------- session: KPIs
def render_kpis(session: Session, prices: tuple[float, float, float]) -> None:
    summary = session_summary(session, prices)
    with st.container(key="kpi-session"):
        cols = st.columns(8)
        cols[0].metric("ターン", summary["turns"])
        cols[1].metric("LLM", summary["llm_calls"])
        cols[2].metric("ツール", summary["tool_calls"])
        cols[3].metric("ツールエラー", summary["tool_errors"],
                       delta=f"run error {summary['run_errors']}" if summary["run_errors"] else None,
                       delta_color="inverse")
        cols[4].metric("売買", summary["trades"])
        cols[5].metric("トークン", fmt_int(summary["total_tokens"]),
                       help=f"入力 {fmt_int(summary['input_tokens'])} / キャッシュ {fmt_int(summary['cached_tokens'])} / "
                            f"出力 {fmt_int(summary['output_tokens'])} / 推論 {fmt_int(summary['reasoning_tokens'])}")
        cache_rate = summary["cached_tokens"] / summary["input_tokens"] if summary["input_tokens"] else 0
        cols[6].metric("キャッシュ率", f"{cache_rate:.0%}")
        cols[7].metric("推定コスト", f"${summary['cost_usd']:.4f}")


# ----------------------------------------------------------- session: timeline
def render_timeline(session: Session, prices: tuple[float, float, float]) -> None:
    if not session.turns:
        st.info("まだターンがありません。")
        return

    c1, c2, c3 = st.columns([3, 1.2, 1.2])
    turn_numbers = [t.turn for t in session.turns]
    selected = c1.pills("ターン", turn_numbers, selection_mode="multi", default=turn_numbers,
                        format_func=lambda n: f"T{n}", key="tl-turns")
    show_reasoning = c2.toggle("💭 推論を表示", value=True, key="tl-reason")
    expand_results = c3.toggle("📦 結果を展開", value=False, key="tl-expand")

    for turn in session.turns:
        if turn.turn not in (selected or []):
            continue
        st.markdown(
            f'<div class="pv-turn"><b>TURN {turn.turn}</b>'
            f'{chip("🕒 " + fmt_time(turn.start_ts))}{status_chip(turn.status)}'
            f'{chip("⏱ " + fmt_ms(turn.duration_ms))}{chip(f"🧠 {len(turn.steps)} LLM", "violet")}'
            f'{chip(f"🔧 {len(turn.tools)} tools", "blue")}'
            f'{chip("🪙 " + fmt_int(sum(s.usage.get("total_tokens", 0) for s in turn.steps)) + " tok")}'
            f'{chip("$" + format(sum(cost_usd(s.usage, prices) for s in turn.steps), ".4f"))}</div>',
            unsafe_allow_html=True,
        )
        with st.chat_message("user"):
            st.markdown(turn.user_text or "_(入力なし)_")

        for step in turn.steps:
            st.markdown(
                f'<div class="pv-step"><span class="pv-label">Step {step.step}</span>'
                f'{chip("LLM " + fmt_ms(step.duration_ms), "violet")}'
                f'{chip(f"context {step.input_item_count} items") if step.input_item_count is not None else ""}'
                f'{usage_chips(step.usage, prices)}</div>',
                unsafe_allow_html=True,
            )
            if show_reasoning and step.reasoning:
                with st.container(border=True, key=f"card-reason-{turn.turn}-{step.step}"):
                    st.markdown('<span class="pv-label" style="color:#8b5cf6">💭 Reasoning</span>',
                                unsafe_allow_html=True)
                    for text in step.reasoning:
                        st.markdown(text)
            elif show_reasoning and any(o.get("type") == "reasoning" for o in step.outputs):
                st.caption("💭 推論は暗号化されています（要約なし）")

            for call in step.tools:
                render_tool_card(session, call, expand_results)

            for i, text in enumerate(step.messages):
                with st.container(border=True, key=f"card-msg-{turn.turn}-{step.step}-{i}"):
                    with st.chat_message("assistant"):
                        st.markdown(text)

        if turn.error:
            with st.container(border=True, key=f"card-err-{turn.turn}"):
                st.error(f"**実行エラー {turn.error.get('error_type')}**: {turn.error.get('error')}")
                with st.expander("Traceback"):
                    st.code(turn.error.get("traceback") or "", language="python")


def render_tool_card(session: Session, call: ToolCall, expanded: bool) -> None:
    with st.container(border=True, key=f"card-tool-{call.status}-{call.call_id}"):
        st.markdown(
            f'<span class="pv-name" style="color:#3b82f6">🔧 {html.escape(call.name)}</span>'
            f'{status_chip(call.status)}{chip("⏱ " + fmt_ms(call.duration_ms))}'
            f'{chip("📦 " + fmt_int(call.result_chars) + " chars")}'
            f'<span class="pv-mono">{html.escape(call.call_id)}</span>',
            unsafe_allow_html=True,
        )
        st.code(json.dumps(call.arguments, ensure_ascii=False, indent=None), language="json", wrap_lines=True)
        label = "🖼️ 返り値 (画像)" if call.image_path or call.image_url else f"📤 返り値 · {call.result_type or '–'}"
        with st.expander(label, expanded=expanded or call.status == "error"):
            render_tool_result(session, call, key=f"tl-{call.call_id}")


# ------------------------------------------------------------ session: analysis
def steps_frame(session: Session, prices: tuple[float, float, float]) -> pd.DataFrame:
    rows = []
    for s in session.steps:
        if s.end_ts is None:  # LLM call still running or aborted by an error
            continue
        u = s.usage
        out, reason = u.get("output_tokens", 0), u.get("reasoning_tokens", 0)
        cached = u.get("cached_tokens", 0)
        rows.append({
            "id": f"T{s.turn}-S{s.step}", "turn": s.turn, "step": s.step,
            "新規入力": max(u.get("input_tokens", 0) - cached, 0), "キャッシュ入力": cached,
            "推論出力": reason, "回答出力": max(out - reason, 0),
            "input_tokens": u.get("input_tokens", 0), "duration_ms": s.duration_ms or 0,
            "context_items": s.input_item_count, "cost": cost_usd(u, prices),
            "tools": ", ".join(c.name for c in s.tools),
        })
    return pd.DataFrame(rows)


def render_analysis(session: Session, prices: tuple[float, float, float]) -> None:
    df = steps_frame(session, prices)
    if df.empty:
        st.info("LLM 呼び出しがまだありません。")
        return
    order = list(df["id"])

    left, right = st.columns(2)
    with left:
        st.markdown("##### 🪙 LLM呼び出しごとのトークン内訳")
        long = df.melt(id_vars=["id", "tools"], value_vars=["新規入力", "キャッシュ入力", "推論出力", "回答出力"],
                       var_name="種類", value_name="tokens")
        chart = alt.Chart(long).mark_bar().encode(
            x=alt.X("id:N", sort=order, title=None),
            y=alt.Y("tokens:Q", title="tokens"),
            color=alt.Color("種類:N", scale=alt.Scale(
                domain=["新規入力", "キャッシュ入力", "推論出力", "回答出力"],
                range=["#3b82f6", "#93c5fd", "#8b5cf6", "#c4b5fd"]), legend=alt.Legend(orient="bottom")),
            tooltip=["id", "種類", alt.Tooltip("tokens:Q", format=","), "tools"],
        ).properties(height=300)
        st.altair_chart(chart, width="stretch")
    with right:
        st.markdown("##### 📈 コンテキスト増加とレイテンシ")
        base = alt.Chart(df).encode(x=alt.X("id:N", sort=order, title=None))
        line = base.mark_line(point=True, color="#3b82f6").encode(
            y=alt.Y("input_tokens:Q", title="入力トークン", axis=alt.Axis(titleColor="#3b82f6")),
            tooltip=["id", alt.Tooltip("input_tokens:Q", format=","), "context_items"])
        bars = base.mark_bar(opacity=.35, color="#8b5cf6").encode(
            y=alt.Y("duration_ms:Q", title="LLM レイテンシ (ms)", axis=alt.Axis(titleColor="#8b5cf6")),
            tooltip=["id", "duration_ms"])
        st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent").properties(height=300),
                        width="stretch")

    st.markdown("##### 🕒 実行タイムライン (Gantt)")
    spans = []
    for s in session.steps:
        if s.start_ts and s.end_ts:
            spans.append({"lane": "🧠 LLM", "start": parse_ts(s.start_ts), "end": parse_ts(s.end_ts),
                          "kind": "LLM", "label": f"T{s.turn}-S{s.step}", "ms": s.duration_ms})
        for c in s.tools:
            if c.start_ts and c.end_ts:
                spans.append({"lane": f"🔧 {c.name}", "start": parse_ts(c.start_ts), "end": parse_ts(c.end_ts),
                              "kind": "tool error" if c.error else "tool", "label": f"T{c.turn}-S{c.step}",
                              "ms": c.duration_ms})
    if spans:
        sdf = pd.DataFrame(spans)
        # Keep very short spans visible.
        sdf["end"] = sdf.apply(lambda r: max(r["end"], r["start"] + pd.Timedelta(milliseconds=150)), axis=1)
        sdf["start"] = sdf["start"].map(lambda d: d.replace(tzinfo=None))
        sdf["end"] = sdf["end"].map(lambda d: d.replace(tzinfo=None))
        gantt = alt.Chart(sdf).mark_bar(cornerRadius=3).encode(
            x=alt.X("start:T", title=None, axis=alt.Axis(format="%H:%M:%S")),
            x2="end:T",
            y=alt.Y("lane:N", title=None, sort=["🧠 LLM"], axis=alt.Axis(labelLimit=260)),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["LLM", "tool", "tool error"],
                                                      range=[COLORS["llm"], COLORS["tool"], COLORS["error"]]),
                            legend=alt.Legend(orient="bottom")),
            tooltip=["label", "lane", alt.Tooltip("ms:Q", title="ms"),
                     alt.Tooltip("start:T", format="%H:%M:%S.%L")],
        ).properties(height=max(140, 44 * sdf["lane"].nunique())).interactive(bind_y=False)
        st.altair_chart(gantt, width="stretch")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("##### 🔧 ツール統計")
        tools = session.tools
        if tools:
            tdf = pd.DataFrame([{
                "tool": c.name, "error": bool(c.error), "ms": c.duration_ms or 0, "chars": c.result_chars or 0,
            } for c in tools])
            stats = tdf.groupby("tool").agg(
                呼び出し=("tool", "size"), エラー=("error", "sum"), 平均ms=("ms", "mean"), 最大ms=("ms", "max"),
                平均返り値chars=("chars", "mean"),
            ).reset_index().sort_values("呼び出し", ascending=False)
            stats["エラー率"] = stats["エラー"] / stats["呼び出し"]
            st.dataframe(stats, hide_index=True, column_config={
                "呼び出し": st.column_config.ProgressColumn(format="%d", min_value=0,
                                                       max_value=int(stats["呼び出し"].max())),
                "エラー率": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "平均ms": st.column_config.NumberColumn(format="%.0f"),
                "平均返り値chars": st.column_config.NumberColumn(format="%.0f"),
            })
        else:
            st.caption("ツール呼び出しなし")
    with right:
        st.markdown("##### 💲 ターン別コスト")
        cost = df.groupby("turn", as_index=False)["cost"].sum()
        cost["turn"] = "T" + cost["turn"].astype(str)
        st.altair_chart(alt.Chart(cost).mark_bar(color="#f59e0b", cornerRadiusEnd=3).encode(
            x=alt.X("cost:Q", title="USD"), y=alt.Y("turn:N", sort=None, title=None),
            tooltip=["turn", alt.Tooltip("cost:Q", format="$.4f")],
        ).properties(height=max(160, 40 * len(cost))), width="stretch")


# --------------------------------------------------------------- session: tools
def render_tools(session: Session) -> None:
    calls = session.tools
    if not calls:
        st.info("ツール呼び出しはありません。")
        return

    c1, c2, c3 = st.columns([3, 1.4, 2])
    names = sorted({c.name for c in calls})
    picked = c1.pills("ツール", names, selection_mode="multi", default=names, key="tools-names")
    status = c2.segmented_control("状態", ["すべて", "ok", "error"], default="すべて", key="tools-status",
                                  required=True)
    query = c3.text_input("引数・返り値を検索", key="tools-q", placeholder="例: 0xabc, token_id ...")

    def match(c: ToolCall) -> bool:
        if c.name not in (picked or []):
            return False
        if status != "すべて" and c.status != status:
            return False
        if query:
            blob = json.dumps([c.arguments, c.result, c.error], ensure_ascii=False, default=str).lower()
            return query.lower() in blob
        return True

    filtered = [c for c in calls if match(c)]
    st.caption(f"{len(filtered)} / {len(calls)} 件　·　行をクリックすると詳細を表示します")
    table = pd.DataFrame([{
        "時刻": fmt_time(c.start_ts), "位置": f"T{c.turn}-S{c.step}", "ツール": c.name, "状態": c.status,
        "引数": compact_json(c.arguments, 80), "ms": c.duration_ms, "chars": c.result_chars,
        "返り値プレビュー": "(画像)" if c.image_path else compact_json(c.result, 100),
    } for c in filtered])
    event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                         key="tools-table", height=min(38 * (len(table) + 1), 360))
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        return
    call = filtered[rows[0]]

    st.markdown(
        f'<span class="pv-name" style="color:#3b82f6">🔧 {html.escape(call.name)}</span>'
        f'{status_chip(call.status)}{chip("T" + str(call.turn) + "-S" + str(call.step))}'
        f'{chip("⏱ " + fmt_ms(call.duration_ms))}<span class="pv-mono">{html.escape(call.call_id)}</span>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True, key="card-reason-detail"):
            st.markdown("**💭 呼び出し前の推論**")
            if call.reasoning:
                for text in call.reasoning:
                    st.markdown(text)
            else:
                st.caption("推論の要約はありません")
        with st.container(border=True):
            st.markdown("**📥 引数**")
            render_value(call.arguments, key=f"args-{call.call_id}")
    with right:
        with st.container(border=True, key=f"card-tool-{call.status}-detail"):
            st.markdown("**📤 返り値**")
            render_tool_result(session, call, key=f"detail-{call.call_id}")


# ----------------------------------------------------------- session: reasoning
def render_reasoning(session: Session) -> None:
    steps = session.steps
    if not any(s.reasoning for s in steps):
        encrypted = any(o.get("type") == "reasoning" for s in steps for o in s.outputs)
        st.info(
            "推論の要約が記録されていません。"
            + ("（推論アイテムは存在しますが暗号化されています）" if encrypted else "")
            + "\n\n`src/config.py` の `REASONING_SUMMARY = \"auto\"` と、推論対応モデルを使っているか確認してください。"
        )
        return

    c1, c2 = st.columns([3, 1])
    query = c1.text_input("推論を検索", key="reason-q", placeholder="キーワードでハイライト・絞り込み")
    only_tools = c2.toggle("ツール呼び出しを伴う推論のみ", key="reason-tools")

    total_reason = sum(s.usage.get("reasoning_tokens", 0) for s in steps)
    st.caption(f"推論トークン合計 {fmt_int(total_reason)}")

    for s in steps:
        if not s.reasoning or (only_tools and not s.tools):
            continue
        joined = "\n\n".join(s.reasoning)
        if query and query.lower() not in joined.lower():
            continue
        with st.container(border=True, key=f"card-reason-tab-{s.turn}-{s.step}"):
            st.markdown(
                f'<span class="pv-label" style="color:#8b5cf6">T{s.turn} · Step {s.step}</span>'
                f'{chip("reasoning " + fmt_int(s.usage.get("reasoning_tokens")) + " tok", "violet")}'
                f'{chip("LLM " + fmt_ms(s.duration_ms))}',
                unsafe_allow_html=True,
            )
            st.markdown(highlight(joined, query))
            actions = [chip(f"🔧 {c.name}({compact_json(c.arguments, 60)})", "error" if c.error else "blue")
                       for c in s.tools]
            actions += [chip("💬 " + compact_json(m, 70)) for m in s.messages]
            if actions:
                st.markdown('<span class="pv-label">→ 次のアクション</span>' + "".join(actions), unsafe_allow_html=True)


# --------------------------------------------------------- session: info & raw
def render_info(session: Session) -> None:
    meta = session.meta
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**モデル**  \n`{meta.get('model', '?')}`")
    c2.markdown(f"**推論設定**  \n`{json.dumps(meta.get('reasoning'), ensure_ascii=False)}`")
    c3.markdown(f"**ログファイル**  \n`{session.path}`")
    with st.expander("📜 システムプロンプト (instructions)"):
        st.code(meta.get("instructions") or "(記録なし)", language="markdown", wrap_lines=True)
    st.markdown("##### 🧰 利用可能なツール")
    for tool in meta.get("tools", []) or []:
        with st.expander(f"🔧 {tool.get('name')}"):
            st.markdown(tool.get("description") or "")
            st.json(tool.get("parameters") or {}, expanded=False)


def render_raw(session: Session) -> None:
    events = session.events
    kinds = sorted({e.get("event") for e in events})
    picked = st.pills("イベント種別", kinds, selection_mode="multi", default=kinds, key="raw-kinds")
    filtered = [e for e in events if e.get("event") in (picked or [])]
    skip = {"ts", "session_id", "event", "turn", "step"}
    table = pd.DataFrame([{
        "時刻": e.get("ts", "")[11:23], "event": e.get("event"), "turn": e.get("turn"), "step": e.get("step"),
        "内容": compact_json({k: v for k, v in e.items() if k not in skip}, 140),
    } for e in filtered])
    event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                         key="raw-table", height=420)
    rows = event.selection.rows if event and event.selection else []
    if rows:
        st.json(filtered[rows[0]], expanded=2)
    st.download_button("⬇️ JSONL をダウンロード", data=session.path.read_bytes(),
                       file_name=session.path.name, mime="application/jsonl")


def render_session(path: Path, prices: tuple[float, float, float]) -> None:
    session = load_session(path)
    start = session.start.strftime("%Y-%m-%d %H:%M:%S") if session.start else "?"
    state = chip("🟢 実行中 / 未終了", "running") if not session.ended else chip("⚪ 終了", "")
    st.markdown(
        f'<div class="pv-hero"><h1>🛰️ {html.escape(session.session_id)}</h1>{state}</div>'
        f'<div class="pv-sub">{start} 開始 · model <code>{html.escape(str(session.meta.get("model", "?")))}</code>'
        f' · {len(session.events)} events</div>',
        unsafe_allow_html=True,
    )
    render_kpis(session, prices)
    tabs = st.tabs(["🧵 タイムライン", "📊 分析", "🔧 ツール", "💭 推論", "⚙️ セッション情報", "🗂️ Raw"])
    with tabs[0]:
        render_timeline(session, prices)
    with tabs[1]:
        render_analysis(session, prices)
    with tabs[2]:
        render_tools(session)
    with tabs[3]:
        render_reasoning(session)
    with tabs[4]:
        render_info(session)
    with tabs[5]:
        render_raw(session)


# --------------------------------------------------------------------- overview
def render_overview(files: list[Path], prices: tuple[float, float, float]) -> None:
    st.markdown('<div class="pv-hero"><h1>🌐 全体サマリー</h1></div>'
                '<div class="pv-sub">全セッションを横断した利用状況</div>', unsafe_allow_html=True)
    sessions = [load_session(p) for p in files]
    df = pd.DataFrame([session_summary(s, prices) for s in sessions])

    with st.container(key="kpi-overview"):
        cols = st.columns(6)
        cols[0].metric("セッション", len(df))
        cols[1].metric("ターン", int(df["turns"].sum()))
        cols[2].metric("ツール呼び出し", int(df["tool_calls"].sum()))
        cols[3].metric("エラー", int(df["tool_errors"].sum() + df["run_errors"].sum()))
        cols[4].metric("総トークン", fmt_int(df["total_tokens"].sum()))
        cols[5].metric("推定コスト", f"${df['cost_usd'].sum():.3f}")

    left, right = st.columns(2)
    with left:
        st.markdown("##### 📅 日別コストとトークン")
        daily = df.groupby("date", as_index=False).agg(cost=("cost_usd", "sum"), tokens=("total_tokens", "sum"),
                                                       sessions=("session_id", "count"))
        st.altair_chart(alt.Chart(daily).mark_bar(color="#f59e0b", cornerRadiusEnd=3, size=28).encode(
            x=alt.X("date:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("cost:Q", title="USD"),
            tooltip=["date", alt.Tooltip("cost:Q", format="$.4f"), alt.Tooltip("tokens:Q", format=","), "sessions"],
        ).properties(height=260), width="stretch")
    with right:
        st.markdown("##### 🔧 ツール利用回数")
        tdf = pd.DataFrame([{"tool": c.name, "状態": "error" if c.error else "ok"}
                            for s in sessions for c in s.tools])
        if not tdf.empty:
            tdf = tdf.groupby(["tool", "状態"], as_index=False).size().rename(columns={"size": "回数"})
            st.altair_chart(alt.Chart(tdf).mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("tool:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                x=alt.X("sum(回数):Q", title="回数"),
                color=alt.Color("状態:N", scale=alt.Scale(domain=["ok", "error"],
                                                         range=[COLORS["tool"], COLORS["error"]]),
                                legend=alt.Legend(orient="bottom")),
                tooltip=["tool", "状態", "回数"],
            ).properties(height=max(200, 34 * tdf["tool"].nunique())), width="stretch")
        else:
            st.caption("ツール呼び出しなし")

    st.markdown("##### 🗂️ セッション一覧　<small>(行をクリックで詳細へ)</small>", unsafe_allow_html=True)
    view = df[["live", "start", "turns", "llm_calls", "tool_calls", "tool_errors", "run_errors", "trades",
               "total_tokens", "cost_usd", "duration_s", "first_message", "model"]].copy()
    view["live"] = view["live"].map({True: "🟢", False: "⚪"})
    view["start"] = view["start"].map(lambda d: d.strftime("%Y-%m-%d %H:%M:%S") if d else "")
    event = st.dataframe(
        view, hide_index=True, selection_mode="single-row", key="overview-table", on_select="rerun",
        column_config={
            "live": st.column_config.TextColumn("", width="small"),
            "start": "開始", "turns": "ターン", "llm_calls": "LLM", "tool_calls": "ツール",
            "tool_errors": "ツールエラー", "run_errors": "実行エラー", "trades": "売買",
            "total_tokens": st.column_config.NumberColumn("トークン", format="%d"),
            "cost_usd": st.column_config.ProgressColumn("コスト", format="$%.4f", min_value=0,
                                                       max_value=float(max(df["cost_usd"].max(), 1e-9))),
            "duration_s": st.column_config.NumberColumn("時間(s)", format="%.0f"),
            "first_message": "最初のメッセージ", "model": "モデル",
        },
    )
    rows = event.selection.rows if event and event.selection else []
    if rows:
        # Widgets in the sidebar are already rendered; switch on the next full run.
        st.session_state["open_session"] = df["path"].iloc[rows[0]]
        st.rerun(scope="app")

    errors = [(s, c) for s in sessions for c in s.tools if c.error]
    if errors:
        st.markdown("##### 🚨 最近のツールエラー")
        for s, c in errors[:15]:
            st.markdown(
                f'{chip(fmt_time(c.start_ts))}{chip(s.session_id)}{chip("🔧 " + c.name, "blue")}'
                f'{chip((c.error or {}).get("error_type") or "", "error")} '
                f'<span class="pv-mono">{html.escape(compact_json((c.error or {}).get("error"), 140))}</span>',
                unsafe_allow_html=True,
            )


# ------------------------------------------------------------------------- main
def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    opts = sidebar()

    if not opts["files"]:
        st.markdown('<div class="pv-hero"><h1>🛰️ PolyViewer</h1></div>', unsafe_allow_html=True)
        st.info(f"ログがまだありません: `{opts['log_dir']}`\n\n"
                "`python src/main.py` でエージェントを実行すると、行動ログがここに記録されます。")
        return

    @st.fragment(run_every=opts["interval"] if opts["live"] else None)
    def body() -> None:
        if opts["mode"] == "🌐 全体":
            render_overview(opts["files"], opts["prices"])
        elif opts["session_path"] is not None:
            render_session(opts["session_path"], opts["prices"])

    body()


main()
