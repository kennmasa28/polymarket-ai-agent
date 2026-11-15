import {
  api, esc, md, reasonHtml, valueHtml, jsonHtml, highlight, toast, openModal, closeModal, fmtMs, fmtInt, fmtUsd,
  fmtTime, fmtDateTime, short, costUsd, getPrices, setPrices, DEFAULT_PRICES, cssVar,
} from "./common.js";

const $ = (id) => document.getElementById(id);
const layout = $("layout");
const view = $("view");
const state = {
  sessions: [], source: "", sessionId: layout.dataset.session || null, session: null, tab: "timeline",
  turns: null, showReasoning: true, expandResults: false, toolFilter: { names: null, status: "all", q: "" },
  reasonQ: "", reasonToolsOnly: false, rawKinds: null, selectedCall: null, charts: [], live: false, timer: null,
};
const COLORS = () => ({
  accent: cssVar("--accent"), violet: cssVar("--violet"), blue: cssVar("--blue"), red: cssVar("--red"), amber: cssVar("--amber"),
  green: cssVar("--green"), cyan: cssVar("--accent-2"), grid: cssVar("--chart-grid"), muted: cssVar("--muted"), faint: cssVar("--faint"),
});

// ------------------------------------------------------------- session list
async function loadSessions() {
  try { state.sessions = (await api("/api/logs/sessions")).items; } catch (e) { toast(e.message, "err"); }
  renderSessionList();
}
function renderSessionList() {
  const q = $("session-search").value.trim().toLowerCase();
  const items = state.sessions.filter((s) => (!state.source || s.source === state.source) &&
    (!q || `${s.title} ${s.session_id}`.toLowerCase().includes(q)));
  const prices = getPrices();
  $("sessions").innerHTML = items.map((s) => `<div class="session-item ${s.session_id === state.sessionId ? "active" : ""}" data-id="${esc(s.session_id)}">
      <div class="t">${s.live ? `<span class="live-dot"></span> ` : ""}${esc(s.title)}</div>
      <div class="m"><span>${esc(fmtDateTime(s.start))}</span><span class="chip">${esc(s.source || "?")}</span><span>${s.turns}T</span>
        ${s.tool_errors + s.run_errors ? `<span class="chip red">⚠ ${s.tool_errors + s.run_errors}</span>` : ""}
        <span>${fmtUsd(sessionCost(s, prices), 3)}</span></div></div>`).join("")
    || `<div class="empty" style="padding:24px 8px">ログがありません</div>`;
  $("go-overview").classList.toggle("primary", !state.sessionId);
}
// Cost of a session summary with the current price settings (usage totals are per session).
function sessionCost(s, prices = getPrices()) { return costUsd({ input_tokens: s.input_tokens, cached_tokens: s.cached_tokens, output_tokens: s.output_tokens }, prices); }

$("sessions").addEventListener("click", (e) => { const it = e.target.closest("[data-id]"); if (it) openSession(it.dataset.id, true); });
$("session-search").addEventListener("input", renderSessionList);
$("source-filter").addEventListener("click", (e) => {
  const b = e.target.closest("[data-src]"); if (!b) return;
  state.source = b.dataset.src;
  $("source-filter").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
  renderSessionList();
  if (!state.sessionId) renderOverview();
});
$("go-overview").addEventListener("click", () => { state.sessionId = null; history.pushState(null, "", "/logs"); stopLive(); renderSessionList(); renderOverview(); });
window.addEventListener("popstate", () => {
  const m = location.pathname.match(/^\/logs\/([\w-]+)/);
  if (m) openSession(m[1]); else { state.sessionId = null; renderSessionList(); renderOverview(); }
});

// -------------------------------------------------------------------- charts
function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; }
function chart(id, config) {
  const el = $(id); if (!el) return;
  const c = COLORS();
  Chart.defaults.color = c.muted; Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.borderColor = c.grid;
  state.charts.push(new Chart(el, config));
}
const baseOpts = (extra = {}) => ({ maintainAspectRatio: false, animation: { duration: 300 },
  plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true } } }, ...extra });

// ------------------------------------------------------------------ overview
async function renderOverview() {
  destroyCharts();
  const prices = getPrices();
  const sessions = state.sessions.filter((s) => !state.source || s.source === state.source);
  const sum = (k) => sessions.reduce((n, s) => n + (s[k] || 0), 0);
  const cost = sessions.reduce((n, s) => n + sessionCost(s, prices), 0);
  view.innerHTML = `<div class="page-head"><div><h1>全体サマリー</h1><p>全セッションを横断した利用状況</p></div>
      <button class="btn sm" id="prices-btn">💲 料金設定</button></div>
    <div class="kpis" style="margin-bottom:16px">
      ${kpi("セッション", sessions.length)}${kpi("ターン", sum("turns"))}${kpi("ツール呼び出し", sum("tool_calls"))}
      ${kpi("エラー", sum("tool_errors") + sum("run_errors"))}${kpi("売買", sum("trades"))}${kpi("総トークン", fmtInt(sum("total_tokens")))}
      ${kpi("推定コスト", fmtUsd(cost, 3))}</div>
    <div class="grid-2" style="margin-bottom:14px">
      <div class="card card-pad"><div class="card-title" style="margin-bottom:8px"><span class="dot"></span>日別コストとトークン</div><div class="chart-box"><canvas id="c-daily"></canvas></div></div>
      <div class="card card-pad"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--blue)"></span>ツール利用回数</div><div class="chart-box"><canvas id="c-tools"></canvas></div></div>
    </div>
    <div class="card card-pad" style="margin-bottom:14px"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--amber)"></span>セッション一覧</div>
      <div class="table-wrap" style="max-height:420px"><table class="grid"><thead><tr><th></th><th>開始</th><th>タイトル</th><th>種別</th><th class="r">ターン</th><th class="r">LLM</th>
        <th class="r">ツール</th><th class="r">エラー</th><th class="r">売買</th><th class="r">トークン</th><th class="r">コスト</th></tr></thead><tbody>
      ${sessions.map((s) => `<tr class="clickable" data-id="${esc(s.session_id)}"><td>${s.live ? `<span class="live-dot"></span>` : ""}</td>
        <td class="num">${esc(fmtDateTime(s.start))}</td><td>${esc(short(s.title, 48))}</td><td><span class="chip">${esc(s.source || "?")}</span></td>
        <td class="r num">${s.turns}</td><td class="r num">${s.llm_calls}</td><td class="r num">${s.tool_calls}</td>
        <td class="r num ${s.tool_errors + s.run_errors ? "neg" : ""}">${s.tool_errors + s.run_errors}</td><td class="r num">${s.trades}</td>
        <td class="r num">${fmtInt(s.total_tokens)}</td><td class="r num">${fmtUsd(sessionCost(s, prices), 4)}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card card-pad" id="errors-card"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--red)"></span>最近のツールエラー</div><div id="errors" class="muted">読み込み中…</div></div>`;
  $("prices-btn").addEventListener("click", openPrices);
  view.querySelector("tbody")?.addEventListener("click", (e) => { const r = e.target.closest("[data-id]"); if (r) openSession(r.dataset.id, true); });

  const c = COLORS();
  const daily = {};
  for (const s of sessions) { const d = (daily[s.date] ||= { cost: 0, tokens: 0 }); d.cost += sessionCost(s, prices); d.tokens += s.total_tokens || 0; }
  const days = Object.keys(daily).sort();
  chart("c-daily", { type: "bar", data: { labels: days, datasets: [
      { label: "コスト (USD)", data: days.map((d) => daily[d].cost), backgroundColor: c.amber, borderRadius: 6, maxBarThickness: 56, yAxisID: "y" },
      { label: "トークン", data: days.map((d) => daily[d].tokens), type: "line", borderColor: c.accent, backgroundColor: c.accent, yAxisID: "y1", tension: .3 }] },
    options: baseOpts({ scales: { y: { ticks: { callback: (v) => "$" + v } }, y1: { position: "right", grid: { display: false } } } }) });

  let calls = [];
  try { calls = (await api("/api/logs/tool-calls")).items; } catch (e) { /* ignore */ }
  const ids = new Set(sessions.map((s) => s.session_id));
  calls = calls.filter((x) => ids.has(x.session_id));
  const names = [...new Set(calls.map((x) => x.name))].sort((a, b) => calls.filter((x) => x.name === b).length - calls.filter((x) => x.name === a).length);
  const count = (n, st) => calls.filter((x) => x.name === n && (st === "error" ? x.status === "error" : x.status !== "error")).length;
  chart("c-tools", { type: "bar", data: { labels: names, datasets: [
      { label: "ok", data: names.map((n) => count(n, "ok")), backgroundColor: c.blue, borderRadius: 4 },
      { label: "error", data: names.map((n) => count(n, "error")), backgroundColor: c.red, borderRadius: 4 }] },
    options: baseOpts({ indexAxis: "y", scales: { x: { stacked: true }, y: { stacked: true } } }) });
  const errors = calls.filter((x) => x.status === "error").sort((a, b) => (b.start_ts || "").localeCompare(a.start_ts || "")).slice(0, 15);
  $("errors").innerHTML = errors.length ? `<div class="stack" style="gap:6px">${errors.map((x) => `<div class="chips clickable" data-id="${esc(x.session_id)}" style="cursor:pointer">
      <span class="chip">${esc(fmtDateTime(x.start_ts))}</span><span class="chip blue mono">${esc(x.name)}</span><span class="chip red">${esc(x.error_type || "")}</span>
      <span class="mono" style="font-size:12px">${esc(short(x.error, 140))}</span></div>`).join("")}</div>` : "ツールエラーはありません 🎉";
  $("errors").addEventListener("click", (e) => { const r = e.target.closest("[data-id]"); if (r) openSession(r.dataset.id, true); });
}
const kpi = (label, value, sub = "") => `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;

function openPrices() {
  const p = getPrices();
  const body = openModal(`<div class="modal-head"><h3>💲 料金設定（USD / 1M tokens）</h3><button class="btn ghost icon" data-close>✕</button></div>
    <div class="stack" style="gap:10px">
      <label class="field"><span>入力</span><input id="p-in" type="number" step="0.01" min="0" value="${p.input}"></label>
      <label class="field"><span>キャッシュ入力</span><input id="p-cache" type="number" step="0.001" min="0" value="${p.cached}"></label>
      <label class="field"><span>出力</span><input id="p-out" type="number" step="0.1" min="0" value="${p.output}"></label>
      <p class="faint" style="margin:0;font-size:12px">コストは推定値です。使用モデルの料金に合わせて調整してください（このブラウザに保存）。</p></div>
    <div class="modal-foot"><button class="btn" id="p-reset">既定に戻す</button><button class="btn primary" id="p-save">保存</button></div>`);
  body.querySelector("#p-reset").addEventListener("click", () => { setPrices(DEFAULT_PRICES); closeModal(); rerender(); });
  body.querySelector("#p-save").addEventListener("click", () => {
    setPrices({ input: +body.querySelector("#p-in").value || 0, cached: +body.querySelector("#p-cache").value || 0, output: +body.querySelector("#p-out").value || 0 });
    closeModal(); rerender();
  });
}
function rerender() { renderSessionList(); if (state.session && state.sessionId) renderSession(); else renderOverview(); }

// ------------------------------------------------------------------- session
async function openSession(id, push = false) {
  try {
    state.session = await api(`/api/logs/sessions/${encodeURIComponent(id)}`);
  } catch (e) { return toast(`開けませんでした: ${e.message}`, "err"); }
  if (state.sessionId !== id) { state.turns = null; state.selectedCall = null; state.toolFilter = { names: null, status: "all", q: "" }; state.rawKinds = null; }
  state.sessionId = id;
  if (push) history.pushState(null, "", `/logs/${id}`);
  layout.classList.remove("show-list");
  renderSessionList();
  renderSession();
  if (state.live && state.session.ended) stopLive();
}

const allSteps = () => state.session.turns.flatMap((t) => t.steps);
const allTools = () => allSteps().flatMap((s) => s.tools);

function renderSession() {
  destroyCharts();
  const s = state.session, sum = s.summary, prices = getPrices();
  const steps = allSteps();
  const usage = steps.reduce((u, st) => { for (const k of ["input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "total_tokens"]) u[k] += st.usage?.[k] || 0; return u; },
    { input_tokens: 0, cached_tokens: 0, output_tokens: 0, reasoning_tokens: 0, total_tokens: 0 });
  const cost = steps.reduce((n, st) => n + costUsd(st.usage, prices), 0);
  const tabs = [["timeline", "🧵 タイムライン"], ["analysis", "📊 分析"], ["tools", "🔧 ツール"], ["reasoning", "💭 推論"], ["info", "⚙️ 情報"], ["raw", "🗂️ Raw"]];
  view.innerHTML = `<div class="page-head"><div style="min-width:0">
      <h1 style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(short(sum.title, 60))}</h1>
      <div class="chips" style="margin-top:6px">${s.ended ? `<span class="chip">⚪ 終了</span>` : `<span class="chip green"><span class="live-dot"></span> 実行中 / 未終了</span>`}
        <span class="chip mono">${esc(s.session_id)}</span><span class="chip accent mono">${esc(s.meta.model || "?")}</span><span class="chip">${esc(s.meta.source || "?")}</span>
        <span class="chip">${esc(fmtDateTime(sum.start))} 開始</span></div></div>
      <div class="chips">
        ${s.meta.source === "ui" ? `<a class="btn sm" href="/c/${esc(s.session_id)}">💬 チャットで開く</a>` : ""}
        <button class="btn sm ${state.live ? "primary" : ""}" id="live-btn">${state.live ? "● ライブ更新中" : "↻ ライブ更新"}</button>
        <button class="btn sm" id="prices-btn">💲</button>
        <a class="btn sm" href="/api/logs/sessions/${esc(s.session_id)}/download">⬇ JSONL</a>
        <button class="btn sm only-mobile" id="list-btn">☰</button></div></div>
    <div class="kpis" style="margin-bottom:16px">
      ${kpi("ターン", sum.turns)}${kpi("LLM", sum.llm_calls)}${kpi("ツール", sum.tool_calls)}
      ${kpi("エラー", `<span class="${sum.tool_errors + sum.run_errors ? "neg" : ""}">${sum.tool_errors + sum.run_errors}</span>`, `tool ${sum.tool_errors} / run ${sum.run_errors}`)}
      ${kpi("売買", sum.trades)}${kpi("トークン", fmtInt(usage.total_tokens), `推論 ${fmtInt(usage.reasoning_tokens)}`)}
      ${kpi("キャッシュ率", usage.input_tokens ? Math.round((usage.cached_tokens / usage.input_tokens) * 100) + "%" : "–")}
      ${kpi("推定コスト", fmtUsd(cost, 4))}</div>
    <div class="tabs" id="tabs" style="margin-bottom:16px">${tabs.map(([k, l]) => `<button class="tab ${k === state.tab ? "active" : ""}" data-tab="${k}">${l}</button>`).join("")}</div>
    <div id="tab-body"></div>`;
  $("tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) { state.tab = b.dataset.tab; renderSession(); } });
  $("prices-btn").addEventListener("click", openPrices);
  $("live-btn").addEventListener("click", () => (state.live ? stopLive() : startLive()));
  $("list-btn")?.addEventListener("click", () => layout.classList.toggle("show-list"));
  ({ timeline: renderTimeline, analysis: renderAnalysis, tools: renderTools, reasoning: renderReasoning, info: renderInfo, raw: renderRaw })[state.tab]();
}

function startLive() {
  state.live = true;
  state.timer = setInterval(async () => {
    if (!state.sessionId) return stopLive();
    const y = document.querySelector(".page-scroll").scrollTop;
    await openSession(state.sessionId);
    document.querySelector(".page-scroll").scrollTop = y;
  }, 4000);
  renderSession();
}
function stopLive() { state.live = false; clearInterval(state.timer); state.timer = null; if (state.session && state.sessionId) renderSession(); }

// ------------------------------------------------------------------ timeline
const statusChip = (st) => ({ ok: `<span class="chip green">✓ OK</span>`, error: `<span class="chip red">✗ ERROR</span>`,
  running: `<span class="chip amber">… 実行中</span>`, awaiting: `<span class="chip amber">⏸ 承認待ち</span>`, rejected: `<span class="chip">⛔ 却下</span>` }[st] || "");

function usageChips(u, prices) {
  if (!u || !Object.keys(u).length) return "";
  return `<span class="chip">in ${fmtInt(u.input_tokens)} (cache ${fmtInt(u.cached_tokens)})</span>
    <span class="chip violet">out ${fmtInt(u.output_tokens)} (reason ${fmtInt(u.reasoning_tokens)})</span><span class="chip">${fmtUsd(costUsd(u, prices), 4)}</span>`;
}

function resultHtml(c) {
  if (c.approval === "rejected") return `<div class="callout">⛔ ユーザーが注文を却下したため実行されていません${c.approval_message ? `<br>理由: ${esc(c.approval_message)}` : ""}</div>`;
  if (c.approval === "pending") return `<div class="callout warn">⏸ ユーザーの承認待ちです</div>`;
  let html = c.approval === "approved" ? `<div class="faint" style="font-size:12px;margin-bottom:6px">✅ ユーザーが承認して実行</div>` : "";
  if (c.error) html += `<div class="callout danger" style="margin-bottom:8px"><b>${esc(c.error.error_type)}</b>: ${esc(c.error.error)}
      <details class="plain" style="margin-top:6px"><summary>Traceback</summary><pre class="json">${esc(c.error.traceback || "")}</pre></details></div>
      <div class="faint" style="font-size:12px">モデルに返された値:</div>`;
  if (c.image) return html + `<img class="chart-img" src="${esc(c.image)}" style="max-width:520px">`;
  return html + valueHtml(c.result) + (c.result_truncated ? `<div class="faint">（長いため一部のみ表示）</div>` : "");
}

function toolCard(c, open) {
  return `<div class="tl-card tool ${c.status}"><div class="label"><span class="mono" style="color:var(--blue);text-transform:none;font-size:13px">🔧 ${esc(c.name)}</span>
      ${statusChip(c.status)}<span class="chip">⏱ ${fmtMs(c.duration_ms)}</span><span class="chip">📦 ${fmtInt(c.result_chars)} chars</span><span class="faint mono" style="text-transform:none">${esc(c.call_id)}</span></div>
    ${jsonHtml(c.arguments ?? {})}
    <details class="plain" style="margin-top:8px" ${open || c.status === "error" ? "open" : ""}><summary>📤 返り値${c.image ? "（画像）" : c.result_type ? ` · ${esc(c.result_type)}` : ""}</summary>
      <div style="margin-top:8px">${resultHtml(c)}</div></details></div>`;
}

function renderTimeline() {
  const s = state.session, prices = getPrices();
  if (!s.turns.length) { $("tab-body").innerHTML = `<div class="empty">まだターンがありません</div>`; return; }
  const sel = state.turns || s.turns.map((t) => t.turn);
  $("tab-body").innerHTML = `<div class="card card-pad" style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
      <div class="chips" id="turn-pills"><span class="muted" style="font-size:12px;margin-right:4px">ターン</span>
        ${s.turns.map((t) => `<button class="chip ${sel.includes(t.turn) ? "accent" : ""}" data-turn="${t.turn}" style="border:0;cursor:pointer">T${t.turn}</button>`).join("")}</div>
      <label class="chips" style="cursor:pointer"><input type="checkbox" id="opt-reason" ${state.showReasoning ? "checked" : ""} style="width:auto"> 💭 推論を表示</label>
      <label class="chips" style="cursor:pointer"><input type="checkbox" id="opt-expand" ${state.expandResults ? "checked" : ""} style="width:auto"> 📦 返り値を展開</label></div>
    <div class="stack">${s.turns.filter((t) => sel.includes(t.turn)).map((t) => {
      const tokens = t.steps.reduce((n, st) => n + (st.usage?.total_tokens || 0), 0);
      const cost = t.steps.reduce((n, st) => n + costUsd(st.usage, prices), 0);
      return `<div class="stack" style="gap:10px"><div class="turn-head"><b>TURN ${t.turn}</b><span class="chip">🕒 ${fmtTime(t.start_ts)}</span>${statusChip(t.status)}
          <span class="chip">⏱ ${fmtMs(t.duration_ms)}</span><span class="chip violet">🧠 ${t.steps.length} LLM</span><span class="chip blue">🔧 ${t.steps.flatMap((x) => x.tools).length} tools</span>
          <span class="chip">🪙 ${fmtInt(tokens)} tok</span><span class="chip">${fmtUsd(cost, 4)}</span></div>
        <div class="msg user" style="justify-content:flex-start"><div class="bubble">${esc(t.user_text)}</div></div>
        ${t.steps.map((st) => `<div class="tl-step"><b style="letter-spacing:.06em">STEP ${st.step}</b><span class="chip violet">LLM ${fmtMs(st.duration_ms)}</span>
            ${st.input_item_count != null ? `<span class="chip">context ${st.input_item_count} items</span>` : ""}${usageChips(st.usage, prices)}</div>
          ${state.showReasoning && st.reasoning.length ? `<div class="tl-card reason"><div class="label" style="color:var(--violet)">💭 Reasoning</div>${st.reasoning.map((r) => `<div class="md">${md(r)}</div>`).join("")}</div>` : ""}
          ${state.showReasoning && st.reasoning_encrypted ? `<div class="faint" style="font-size:12px">💭 推論は暗号化されています（要約なし）</div>` : ""}
          ${st.tools.map((c) => toolCard(c, state.expandResults)).join("")}
          ${st.messages.map((m) => `<div class="tl-card msg"><div class="label muted">💬 Assistant</div><div class="md">${md(m)}</div></div>`).join("")}`).join("")}
        ${t.error ? `<div class="tl-card tool error"><div class="label" style="color:var(--red)">実行エラー ${esc(t.error.error_type)}</div>${esc(t.error.error)}
          <details class="plain"><summary>Traceback</summary><pre class="json">${esc(t.error.traceback || "")}</pre></details></div>` : ""}</div>`;
    }).join("")}</div>`;
  $("turn-pills").addEventListener("click", (e) => {
    const b = e.target.closest("[data-turn]"); if (!b) return;
    const n = +b.dataset.turn, cur = state.turns || s.turns.map((t) => t.turn);
    state.turns = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n];
    renderTimeline();
  });
  $("opt-reason").addEventListener("change", (e) => { state.showReasoning = e.target.checked; renderTimeline(); });
  $("opt-expand").addEventListener("change", (e) => { state.expandResults = e.target.checked; renderTimeline(); });
}

// ------------------------------------------------------------------ analysis
function renderAnalysis() {
  const steps = allSteps().filter((st) => st.end_ts);
  if (!steps.length) { $("tab-body").innerHTML = `<div class="empty">LLM 呼び出しがまだありません</div>`; return; }
  const prices = getPrices(), c = COLORS();
  const labels = steps.map((st) => `T${st.turn}-S${st.step}`);
  $("tab-body").innerHTML = `<div class="grid-2" style="margin-bottom:14px">
      <div class="card card-pad"><div class="card-title" style="margin-bottom:8px"><span class="dot"></span>LLM呼び出しごとのトークン内訳</div><div class="chart-box" style="height:280px"><canvas id="c-tokens"></canvas></div></div>
      <div class="card card-pad"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--blue)"></span>コンテキスト増加とレイテンシ</div><div class="chart-box" style="height:280px"><canvas id="c-ctx"></canvas></div></div></div>
    <div class="card card-pad" style="margin-bottom:14px"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--violet)"></span>実行タイムライン（Gantt）</div>
      <div class="chart-box" id="gantt-box"><canvas id="c-gantt"></canvas></div></div>
    <div class="split"><div class="card card-pad"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--blue)"></span>ツール統計</div><div id="tool-stats"></div></div>
      <div class="card card-pad"><div class="card-title" style="margin-bottom:8px"><span class="dot" style="background:var(--amber)"></span>ターン別コスト</div><div class="chart-box" id="cost-box"><canvas id="c-cost"></canvas></div></div></div>`;

  const u = (st, k) => st.usage?.[k] || 0;
  chart("c-tokens", { type: "bar", data: { labels, datasets: [
      { label: "新規入力", data: steps.map((st) => Math.max(u(st, "input_tokens") - u(st, "cached_tokens"), 0)), backgroundColor: c.blue },
      { label: "キャッシュ入力", data: steps.map((st) => u(st, "cached_tokens")), backgroundColor: c.blue + "66" },
      { label: "推論出力", data: steps.map((st) => u(st, "reasoning_tokens")), backgroundColor: c.violet },
      { label: "回答出力", data: steps.map((st) => Math.max(u(st, "output_tokens") - u(st, "reasoning_tokens"), 0)), backgroundColor: c.violet + "77" }] },
    options: baseOpts({ scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true } },
      plugins: { ...baseOpts().plugins, tooltip: { callbacks: { afterBody: (it) => `tools: ${steps[it[0].dataIndex].tools.map((x) => x.name).join(", ") || "–"}` } } } }) });
  chart("c-ctx", { data: { labels, datasets: [
      { type: "line", label: "入力トークン", data: steps.map((st) => u(st, "input_tokens")), borderColor: c.blue, backgroundColor: c.blue, yAxisID: "y", tension: .3 },
      { type: "bar", label: "LLM レイテンシ (ms)", data: steps.map((st) => st.duration_ms || 0), backgroundColor: c.violet + "55", borderRadius: 4, yAxisID: "y1" }] },
    options: baseOpts({ scales: { x: { grid: { display: false } }, y: { title: { display: true, text: "tokens" } }, y1: { position: "right", grid: { display: false }, title: { display: true, text: "ms" } } } }) });

  // Gantt: seconds since the session start.
  const t0 = new Date(state.session.summary.start).getTime();
  const spans = [];
  for (const st of allSteps()) {
    if (st.start_ts && st.end_ts) spans.push({ lane: "🧠 LLM", kind: "LLM", s: st.start_ts, e: st.end_ts, label: `T${st.turn}-S${st.step}`, ms: st.duration_ms });
    for (const x of st.tools) if (x.start_ts && x.end_ts) spans.push({ lane: `🔧 ${x.name}`, kind: x.status === "error" ? "error" : "tool", s: x.start_ts, e: x.end_ts, label: `T${x.turn}-S${x.step}`, ms: x.duration_ms });
  }
  const lanes = ["🧠 LLM", ...[...new Set(spans.filter((x) => x.kind !== "LLM").map((x) => x.lane))]];
  $("gantt-box").style.height = Math.max(160, 40 * lanes.length + 60) + "px";
  const pt = (x) => { const a = (new Date(x.s).getTime() - t0) / 1000, b = (new Date(x.e).getTime() - t0) / 1000; return { y: x.lane, x: [a, Math.max(b, a + 0.15)], meta: x }; };
  const ds = (kind, label, color) => ({ label, data: spans.filter((x) => x.kind === kind).map(pt), backgroundColor: color, borderRadius: 4, borderSkipped: false, barPercentage: .7, grouped: false });
  chart("c-gantt", { type: "bar", data: { labels: lanes, datasets: [ds("LLM", "LLM", c.violet), ds("tool", "tool", c.blue), ds("error", "tool error", c.red)] },
    options: baseOpts({ indexAxis: "y", scales: { x: { type: "linear", title: { display: true, text: "セッション開始からの秒数" } }, y: { type: "category", labels: lanes, grid: { display: false } } },
      plugins: { ...baseOpts().plugins, tooltip: { callbacks: { label: (it) => `${it.raw.meta.label} ${it.raw.meta.lane}: ${fmtMs(it.raw.meta.ms)}` } } } }) });

  const tools = allTools();
  const stats = {};
  for (const x of tools) { const r = (stats[x.name] ||= { n: 0, err: 0, ms: 0, max: 0, chars: 0 }); r.n++; r.err += x.status === "error"; r.ms += x.duration_ms || 0; r.max = Math.max(r.max, x.duration_ms || 0); r.chars += x.result_chars || 0; }
  const rows = Object.entries(stats).sort((a, b) => b[1].n - a[1].n);
  const maxN = Math.max(1, ...rows.map((r) => r[1].n));
  $("tool-stats").innerHTML = rows.length ? `<div class="table-wrap"><table class="grid"><thead><tr><th>ツール</th><th>回数</th><th class="r">エラー率</th><th class="r">平均</th><th class="r">最大</th><th class="r">平均chars</th></tr></thead><tbody>
    ${rows.map(([n, r]) => `<tr><td class="mono">${esc(n)}</td><td><div class="bar-cell"><div class="bar" style="width:${(r.n / maxN) * 90}px"></div>${r.n}</div></td>
      <td class="r num ${r.err ? "neg" : ""}">${Math.round((r.err / r.n) * 100)}%</td><td class="r num">${fmtMs(r.ms / r.n)}</td><td class="r num">${fmtMs(r.max)}</td><td class="r num">${fmtInt(r.chars / r.n)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="muted">ツール呼び出しなし</div>`;

  const turns = state.session.turns;
  $("cost-box").style.height = Math.max(160, 34 * turns.length + 50) + "px";
  chart("c-cost", { type: "bar", data: { labels: turns.map((t) => `T${t.turn}`), datasets: [{ label: "USD", data: turns.map((t) => t.steps.reduce((n, st) => n + costUsd(st.usage, prices), 0)), backgroundColor: c.amber, borderRadius: 5 }] },
    options: baseOpts({ indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (it) => fmtUsd(it.parsed.x, 4) } } } }) });
}

// --------------------------------------------------------------------- tools
function renderTools() {
  const calls = allTools();
  if (!calls.length) { $("tab-body").innerHTML = `<div class="empty">ツール呼び出しはありません</div>`; return; }
  const names = [...new Set(calls.map((x) => x.name))].sort();
  const f = state.toolFilter; const picked = f.names || names;
  const match = (x) => picked.includes(x.name) && (f.status === "all" || x.status === f.status) &&
    (!f.q || JSON.stringify([x.arguments, x.result, x.error]).toLowerCase().includes(f.q.toLowerCase()));
  const list = calls.filter(match);
  $("tab-body").innerHTML = `<div class="card card-pad" style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:12px">
      <div class="chips" id="tool-names">${names.map((n) => `<button class="chip ${picked.includes(n) ? "blue" : ""} mono" data-name="${esc(n)}" style="border:0;cursor:pointer">${esc(n)}</button>`).join("")}</div>
      <div class="seg" id="tool-status">${["all", "ok", "error", "rejected"].map((s) => `<button class="${f.status === s ? "active" : ""}" data-s="${s}">${s === "all" ? "すべて" : s}</button>`).join("")}</div>
      <input id="tool-q" placeholder="引数・返り値を検索（例: 0xabc, token_id）" value="${esc(f.q)}" style="flex:1;min-width:200px"></div>
    <div class="muted" style="font-size:12px;margin-bottom:6px">${list.length} / ${calls.length} 件 · 行をクリックすると詳細を表示します</div>
    <div class="card" style="margin-bottom:14px"><div class="table-wrap" style="border:0"><table class="grid"><thead><tr><th>時刻</th><th>位置</th><th>ツール</th><th>状態</th><th>引数</th>
      <th class="r">ms</th><th class="r">chars</th><th>返り値</th></tr></thead><tbody id="tool-rows">
      ${list.map((x) => `<tr class="clickable ${x.call_id === state.selectedCall ? "selected" : ""}" data-call="${esc(x.call_id)}"><td class="num">${fmtTime(x.start_ts)}</td><td class="num">T${x.turn}-S${x.step}</td>
        <td class="mono">${esc(x.name)}</td><td>${statusChip(x.status)}</td><td class="mono" style="font-size:12px">${esc(short(x.arguments, 60))}</td>
        <td class="r num">${x.duration_ms ?? "–"}</td><td class="r num">${fmtInt(x.result_chars)}</td><td style="font-size:12px" class="muted">${esc(x.image ? "(画像)" : short(x.result, 70))}</td></tr>`).join("")}
      </tbody></table></div></div><div id="tool-detail"></div>`;
  $("tool-names").addEventListener("click", (e) => { const b = e.target.closest("[data-name]"); if (!b) return;
    f.names = picked.includes(b.dataset.name) ? picked.filter((n) => n !== b.dataset.name) : [...picked, b.dataset.name]; renderTools(); });
  $("tool-status").addEventListener("click", (e) => { const b = e.target.closest("[data-s]"); if (b) { f.status = b.dataset.s; renderTools(); } });
  $("tool-q").addEventListener("change", (e) => { f.q = e.target.value.trim(); renderTools(); });
  $("tool-rows").addEventListener("click", (e) => { const r = e.target.closest("[data-call]"); if (r) { state.selectedCall = r.dataset.call; renderTools(); $("tool-detail").scrollIntoView({ behavior: "smooth" }); } });
  const sel = calls.find((x) => x.call_id === state.selectedCall);
  if (sel) $("tool-detail").innerHTML = `<div class="chips" style="margin-bottom:10px"><span class="mono" style="font-weight:700;color:var(--blue)">🔧 ${esc(sel.name)}</span>${statusChip(sel.status)}
      <span class="chip">T${sel.turn}-S${sel.step}</span><span class="chip">⏱ ${fmtMs(sel.duration_ms)}</span><span class="chip mono">${esc(sel.call_id)}</span></div>
    <div class="split"><div class="stack"><div class="tl-card reason"><div class="label" style="color:var(--violet)">💭 呼び出し前の推論</div>
        ${sel.reasoning?.length ? sel.reasoning.map((r) => `<div class="md">${md(r)}</div>`).join("") : `<span class="muted">推論の要約はありません</span>`}</div>
      <div class="tl-card"><div class="label">📥 引数</div>${valueHtml(sel.arguments)}</div></div>
      <div class="tl-card tool ${sel.status}"><div class="label">📤 返り値</div>${resultHtml(sel)}</div></div>`;
}

// ------------------------------------------------------------------ reasoning
function renderReasoning() {
  const steps = allSteps();
  if (!steps.some((st) => st.reasoning.length)) {
    const enc = steps.some((st) => st.reasoning_encrypted);
    $("tab-body").innerHTML = `<div class="callout info">推論の要約が記録されていません${enc ? "（推論アイテムは存在しますが暗号化されています）" : ""}。<br>
      <code>src/config.py</code> の <code>REASONING_SUMMARY = "auto"</code> と、推論対応モデルを使っているか確認してください。</div>`;
    return;
  }
  const q = state.reasonQ;
  const list = steps.filter((st) => st.reasoning.length && (!state.reasonToolsOnly || st.tools.length) && (!q || st.reasoning.join("\n").toLowerCase().includes(q.toLowerCase())));
  const total = steps.reduce((n, st) => n + (st.usage?.reasoning_tokens || 0), 0);
  $("tab-body").innerHTML = `<div class="card card-pad" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
      <input id="reason-q" placeholder="推論を検索（ハイライト・絞り込み）" value="${esc(q)}" style="flex:1;min-width:220px">
      <label class="chips" style="cursor:pointer"><input type="checkbox" id="reason-tools" ${state.reasonToolsOnly ? "checked" : ""} style="width:auto"> ツール呼び出しを伴う推論のみ</label>
      <span class="chip violet">推論トークン合計 ${fmtInt(total)}</span></div>
    <div class="stack">${list.map((st) => `<div class="tl-card reason"><div class="label" style="color:var(--violet)">T${st.turn} · STEP ${st.step}
        <span class="chip violet">reasoning ${fmtInt(st.usage?.reasoning_tokens)} tok</span><span class="chip">LLM ${fmtMs(st.duration_ms)}</span></div>
      <div style="white-space:pre-wrap">${highlight(st.reasoning.join("\n\n"), q)}</div>
      ${st.tools.length || st.messages.length ? `<div class="chips" style="margin-top:10px"><b style="font-size:12px">→ 次のアクション</b>
        ${st.tools.map((x) => `<span class="chip ${x.status === "error" ? "red" : "blue"} mono">🔧 ${esc(x.name)}(${esc(short(x.arguments, 50))})</span>`).join("")}
        ${st.messages.map((m) => `<span class="chip">💬 ${esc(short(m, 70))}</span>`).join("")}</div>` : ""}</div>`).join("") || `<div class="empty">該当する推論はありません</div>`}</div>`;
  $("reason-q").addEventListener("change", (e) => { state.reasonQ = e.target.value.trim(); renderReasoning(); });
  $("reason-tools").addEventListener("change", (e) => { state.reasonToolsOnly = e.target.checked; renderReasoning(); });
}

// ------------------------------------------------------------------ info / raw
function renderInfo() {
  const m = state.session.meta;
  $("tab-body").innerHTML = `<div class="card card-pad" style="margin-bottom:14px"><dl class="kv">
      <dt>モデル</dt><dd class="mono">${esc(m.model || "?")}</dd><dt>推論設定</dt><dd class="mono">${esc(JSON.stringify(m.reasoning))}</dd>
      <dt>起動元</dt><dd>${esc(m.source || "?")}</dd><dt>ログファイル</dt><dd class="mono">${esc(m.path)}</dd></dl></div>
    <div class="card card-pad" style="margin-bottom:14px"><details class="plain"><summary>📜 システムプロンプト（instructions）</summary>
      <pre class="json" style="max-height:520px">${esc(m.instructions || "(記録なし)")}</pre></details></div>
    <div class="card card-pad"><div class="card-title" style="margin-bottom:10px"><span class="dot"></span>利用可能なツール</div>
      <div class="stack" style="gap:8px">${(m.tools || []).map((t) => `<details class="tl-card"><summary class="mono" style="cursor:pointer;font-weight:700">🔧 ${esc(t.name)}</summary>
        <div class="md muted" style="margin:8px 0">${md(t.description || "")}</div>${jsonHtml(t.parameters || {})}</details>`).join("")}</div></div>`;
}

async function renderRaw() {
  $("tab-body").innerHTML = `<div class="skeleton" style="height:300px"></div>`;
  let events;
  try { events = (await api(`/api/logs/sessions/${state.sessionId}/events`)).items; } catch (e) { $("tab-body").innerHTML = `<div class="callout danger">${esc(e.message)}</div>`; return; }
  const kinds = [...new Set(events.map((e) => e.event))].sort();
  const picked = state.rawKinds || kinds;
  const list = events.filter((e) => picked.includes(e.event));
  const skip = new Set(["ts", "session_id", "event", "turn", "step"]);
  $("tab-body").innerHTML = `<div class="card card-pad chips" id="raw-kinds" style="margin-bottom:12px">${kinds.map((k) => `<button class="chip ${picked.includes(k) ? "accent" : ""}" data-k="${esc(k)}" style="border:0;cursor:pointer">${esc(k)}</button>`).join("")}</div>
    <div class="card"><div class="table-wrap" style="max-height:600px;border:0"><table class="grid"><thead><tr><th>時刻</th><th>event</th><th class="r">turn</th><th class="r">step</th><th>内容</th></tr></thead>
    <tbody id="raw-rows">${list.map((e, i) => `<tr class="clickable" data-i="${i}"><td class="num">${esc((e.ts || "").slice(11, 23))}</td><td><span class="chip">${esc(e.event)}</span></td>
      <td class="r">${e.turn ?? ""}</td><td class="r">${e.step ?? ""}</td>
      <td class="mono" style="font-size:12px">${esc(short(Object.fromEntries(Object.entries(e).filter(([k]) => !skip.has(k))), 140))}</td></tr>`).join("")}</tbody></table></div></div>`;
  $("raw-kinds").addEventListener("click", (e) => { const b = e.target.closest("[data-k]"); if (!b) return;
    state.rawKinds = picked.includes(b.dataset.k) ? picked.filter((k) => k !== b.dataset.k) : [...picked, b.dataset.k]; renderRaw(); });
  $("raw-rows").addEventListener("click", (e) => { const r = e.target.closest("[data-i]"); if (!r) return;
    const ev = list[+r.dataset.i];
    openModal(`<div class="modal-head"><h3>${esc(ev.event)}</h3><button class="btn ghost icon" data-close>✕</button></div>${jsonHtml(ev)}`, { wide: true }); });
}

view.addEventListener("click", (e) => { const img = e.target.closest(".chart-img"); if (img) openModal(`<img src="${esc(img.src)}" style="width:100%;border-radius:12px;background:#fff">`, { wide: true }); });
window.addEventListener("pa-theme", () => rerender());

// ---------------------------------------------------------------------- init
loadSessions().then(() => { if (state.sessionId) openSession(state.sessionId); else renderOverview(); });
