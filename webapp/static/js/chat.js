import {
  api, esc, md, reasonHtml, valueHtml, jsonHtml, toast, openModal, imageModal, fmtMs, fmtInt, fmtUsd,
  fmtSigned, fmtPct, fmtPrice, pnlClass, short, relTime, costUsd,
} from "./common.js";

const ORDER_TOOLS = new Set(["buy_token", "sell_token"]);
const QUICK = [
  ["📋", "ポートフォリオ確認", "現在のポートフォリオを確認して、ポジションごとの損益を表にまとめて"],
  ["🔥", "注目マーケット", "直近24時間で取引量の多い注目イベントを教えて"],
  ["🤖", "AI関連を探す", "AI関連で取引量の多いマーケットを探して、価格推移も見せて"],
  ["🛡️", "リスク評価", "保有ポジションのリスクを評価して、気になる点を教えて"],
];

const $ = (id) => document.getElementById(id);
const layout = $("layout");
const state = {
  convId: layout.dataset.conversation || null,
  data: null,
  running: false,
  conversations: [],
  portfolio: null,
  decisions: {},
};

// ------------------------------------------------------------------ settings
const settings = {
  get model() { return localStorage.getItem("pa-model") || layout.dataset.defaultModel; },
  get effort() { return localStorage.getItem("pa-effort") || ""; },
};
$("set-model").value = settings.model;
$("set-effort").value = settings.effort;
$("set-model").addEventListener("change", (e) => { localStorage.setItem("pa-model", e.target.value.trim()); updateModelChip(); });
$("set-effort").addEventListener("change", (e) => { localStorage.setItem("pa-effort", e.target.value); updateModelChip(); });
$("open-settings").addEventListener("click", () => $("settings").classList.toggle("hidden"));
document.addEventListener("click", (e) => {
  if (!$("settings").contains(e.target) && !$("open-settings").contains(e.target)) $("settings").classList.add("hidden");
});
function updateModelChip() { $("chat-model").textContent = settings.model + (settings.effort ? ` · ${settings.effort}` : ""); }
updateModelChip();

// ------------------------------------------------------------- conversations
async function loadConversations() {
  try {
    const data = await api("/api/conversations");
    state.conversations = data.items;
  } catch (e) { toast(e.message, "err"); }
  renderConversations();
}

function renderConversations() {
  const q = $("conv-search").value.trim().toLowerCase();
  const items = state.conversations.filter((c) => !q || (c.title || "").toLowerCase().includes(q));
  if (!items.length) { $("conv-list").innerHTML = `<div class="empty" style="padding:24px 10px">会話はまだありません</div>`; return; }
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 864e5).toDateString();
  const group = (c) => { const d = new Date(c.start).toDateString(); return d === today ? "今日" : d === yesterday ? "昨日" : c.date; };
  let html = "", last = null;
  for (const c of items) {
    const g = group(c);
    if (g !== last) { html += `<div class="conv-group">${esc(g)}</div>`; last = g; }
    html += `<a class="conv-item ${c.session_id === state.convId ? "active" : ""}" href="/c/${esc(c.session_id)}" data-id="${esc(c.session_id)}">
      <div class="t">${esc(c.title)}</div>
      <div class="m"><span>${c.turns}ターン</span>${c.trades ? `<span>💱 ${c.trades}</span>` : ""}<span>${esc(relTime(c.end))}</span></div></a>`;
  }
  $("conv-list").innerHTML = html;
}

$("conv-list").addEventListener("click", (e) => {
  const item = e.target.closest(".conv-item");
  if (!item) return;
  e.preventDefault();
  layout.classList.remove("show-convs");
  openConversation(item.dataset.id, true);
});
$("conv-search").addEventListener("input", renderConversations);
$("new-chat").addEventListener("click", () => { layout.classList.remove("show-convs"); newConversation(); });
$("toggle-convs").addEventListener("click", () => layout.classList.toggle("show-convs"));
$("toggle-side").addEventListener("click", () => layout.classList.toggle("show-side"));

function newConversation() {
  if (state.running) return toast("エージェントの実行中です", "err");
  state.convId = null; state.data = null; state.decisions = {};
  history.pushState(null, "", "/");
  renderThread(); renderConversations(); renderStats();
  $("input").focus();
}

async function openConversation(id, push = false) {
  if (state.running && id !== state.convId) return toast("エージェントの実行中です", "err");
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(id)}`);
    state.convId = id; state.data = data;
    if (push) history.pushState(null, "", `/c/${id}`);
    renderThread(); renderConversations(); renderStats();
    if (data.active_run && !state.running) streamRun(data.active_run);
  } catch (e) {
    toast(`会話を開けませんでした: ${e.message}`, "err");
    if (push === false) newConversation();
  }
}
window.addEventListener("popstate", () => {
  const m = location.pathname.match(/^\/c\/([\w-]+)/);
  if (m) openConversation(m[1]); else newConversation();
});

// ------------------------------------------------------------------- thread
function renderThread() {
  const thread = $("thread");
  const data = state.data;
  $("chat-title").textContent = data?.turns?.[0] ? short(data.turns[0].user_text, 48) : "新しい会話";
  $("open-log").classList.toggle("hidden", !state.convId);
  if (state.convId) $("open-log").href = `/logs/${state.convId}`;

  if (!data || !data.turns.length) {
    thread.innerHTML = `<div class="welcome"><h1>何をお手伝いしましょう？</h1>
      <p>マーケットの調査、ポジションの分析、注文の提案まで。注文は必ずあなたの承認を経て実行されます。</p>
      <div class="suggestions">${QUICK.map(([i, t, p]) => `<button class="suggestion" data-prompt="${esc(p)}"><b>${i} ${esc(t)}</b><span>${esc(p)}</span></button>`).join("")}</div></div>`;
  } else {
    thread.innerHTML = data.turns.map(turnHtml).join("") + pendingHtml(data.pending || []);
  }
  updateComposer();
  scrollBottom(false);
}

function turnHtml(turn) {
  const steps = turn.steps;
  const tools = steps.flatMap((s) => s.tools);
  const messages = steps.flatMap((s) => s.messages).filter(Boolean);
  const images = tools.filter((c) => c.image);
  const orders = tools.filter((c) => ORDER_TOOLS.has(c.name));
  const activity = steps.length ? `<details class="activity">
      <summary>🧠 思考とツール <span class="chip">${steps.length} steps</span><span class="chip">${tools.length} tools</span>${turn.duration_ms ? `<span class="chip">${fmtMs(turn.duration_ms)}</span>` : ""}</summary>
      <div class="steps">${steps.map(stepHtml).join("")}</div></details>` : "";
  let content = messages.map((m) => `<div class="md">${md(m)}</div>`).join("");
  if (turn.error) content += `<div class="callout danger">エラー: ${esc(turn.error.error_type)}: ${esc(turn.error.error)}</div>`;
  else if (!messages.length && turn.status === "running") content += `<span class="muted">（応答が記録されていません）</span>`;
  return `<div class="msg user"><div class="bubble">${esc(turn.user_text)}</div></div>
    <div class="msg agent"><div class="avatar">◆</div><div class="body">${activity}
      ${content ? `<div class="content">${content}</div>` : ""}
      ${images.map((c) => `<img class="chart-img" src="${esc(c.image)}" alt="${esc(c.name)}" data-caption="${esc(c.name + " " + short(c.arguments, 60))}">`).join("")}
      ${orders.map(orderCardHtml).join("")}
    </div></div>`;
}

function stepHtml(step) {
  return `<div><div class="step-label">STEP ${step.step} · LLM ${fmtMs(step.duration_ms)}</div>
    ${step.reasoning.map((r) => `<div class="reason">${reasonHtml(r)}</div>`).join("")}
    ${step.reasoning_encrypted ? `<div class="faint" style="font-size:12px">推論は暗号化されています</div>` : ""}
    ${step.tools.length ? `<div class="tool-pills" style="margin-top:6px">${step.tools.map((c) =>
      `<button class="tool-pill" data-call="${esc(c.call_id)}"><span class="st ${c.status}"></span>${esc(c.name)}<span class="ms">${fmtMs(c.duration_ms)}</span></button>`).join("")}</div>` : ""}</div>`;
}

function orderOutcome(c) {
  if (c.approval === "rejected") return ["neutral", "⛔ 却下（未発注）"];
  if (c.approval === "pending") return ["neutral", "⏸ 承認待ち"];
  if (c.error) return ["ng", `✗ エラー: ${c.error.error}`];
  const r = c.result && typeof c.result === "object" ? c.result : {};
  if (r.success === false || r.errorMsg || r.error_msg) return ["ng", `✗ 不成立: ${r.errorMsg || r.error_msg || "失敗"}`];
  if (!c.end_ts) return ["neutral", "… 実行中"];
  return ["ok", "✅ 注文送信済み"];
}
const sideOf = (tool) => (tool === "buy_token" ? "BUY" : "SELL");
const amountOf = (tool, a = {}) => (tool === "buy_token" ? `${a.amount_usd ?? "?"} USDC` : `${a.shares ?? "?"} shares`);
function orderCardHtml(c) {
  const [kind, label] = orderOutcome(c);
  const a = c.arguments || {};
  return `<div class="order-card ${kind}"><span class="side-badge ${sideOf(c.name)}">${sideOf(c.name)}</span>
    <span class="chip mono">token ${esc(short(a.token_id, 18))}</span><span class="chip blue">${esc(amountOf(c.name, a))}</span><span>${esc(label)}</span></div>`;
}

function positionFor(tokenId) {
  return (state.portfolio?.positions || []).find((p) => String(p.token_id) === String(tokenId));
}

function pendingHtml(pending) {
  if (!pending.length) return "";
  return `<div class="msg agent"><div class="avatar warn">!</div><div class="body"><div class="approval"><div class="approval-inner">
    <div><b>注文の承認が必要です</b><div class="muted" style="font-size:13px">内容を確認して、発注するか却下してください。FAK 成行注文のため、一部のみ約定したり価格が変動する可能性があります。</div></div>
    ${pending.map((o) => {
      const side = sideOf(o.tool); const a = o.arguments || {}; const pos = positionFor(a.token_id);
      const d = state.decisions[o.call_id];
      return `<div class="stack" style="gap:8px" data-order="${esc(o.call_id)}">
        <div class="approval-order"><span class="side-badge ${side}" style="font-size:15px">${side}</span>
          <div style="min-width:0"><div class="mono" style="font-size:12px;word-break:break-all">token ${esc(a.token_id)}</div>
            ${pos ? `<div class="muted" style="font-size:12px">保有中: ${esc(pos.title)} (${esc(pos.token_name)}) · ${pos.size.toFixed(2)} @ 平均 ${fmtPrice(pos.avr_price)} / 現在 ${fmtPrice(pos.price)}</div>` : ""}</div>
          <div class="amt">${esc(amountOf(o.tool, a))}</div></div>
        <input class="note" placeholder="却下理由（任意・エージェントに伝えます）" value="${esc(d?.note || "")}">
        <div class="approval-actions">
          <button class="btn success" data-decide="approve">✅ 承認して発注</button>
          <button class="btn" data-decide="reject">❌ 却下</button></div>
        ${d ? `<div class="muted" style="font-size:12px">${d.approve ? "✅ 承認を選択済み" : "⛔ 却下を選択済み"}</div>` : ""}
      </div>`;
    }).join("")}</div></div></div></div>`;
}

$("thread").addEventListener("click", async (e) => {
  const sug = e.target.closest(".suggestion");
  if (sug) return send(sug.dataset.prompt);
  const pill = e.target.closest(".tool-pill");
  if (pill) return showToolCall(pill.dataset.call);
  const img = e.target.closest(".chart-img");
  if (img) return imageModal(img.src, img.dataset.caption);
  const decide = e.target.closest("[data-decide]");
  if (decide) {
    const box = decide.closest("[data-order]");
    state.decisions[box.dataset.order] = { approve: decide.dataset.decide === "approve", note: box.querySelector(".note").value.trim() };
    const pending = state.data?.pending || [];
    if (pending.every((o) => state.decisions[o.call_id])) submitDecisions();
    else renderThread();
  }
});

function findCall(callId) {
  for (const t of state.data?.turns || []) for (const s of t.steps) for (const c of s.tools) if (c.call_id === callId) return c;
  return null;
}

function showToolCall(callId) {
  const c = findCall(callId);
  if (!c) return;
  let result;
  if (c.approval === "rejected") result = `<div class="callout">⛔ ユーザーが却下しました${c.approval_message ? `：${esc(c.approval_message)}` : ""}</div>`;
  else if (c.error) result = `<div class="callout danger"><b>${esc(c.error.error_type)}</b>: ${esc(c.error.error)}</div>`;
  else if (c.image) result = `<img class="chart-img" src="${esc(c.image)}" style="width:100%">`;
  else result = valueHtml(c.result) + (c.result_truncated ? `<div class="faint">（長いため一部のみ表示）</div>` : "");
  openModal(`<div class="modal-head"><h3 class="mono">🔧 ${esc(c.name)}</h3><button class="btn ghost icon" data-close>✕</button></div>
    <div class="chips" style="margin-bottom:12px"><span class="chip ${c.status === "ok" ? "green" : c.status === "error" ? "red" : "amber"}">${esc(c.status)}</span>
      <span class="chip">⏱ ${fmtMs(c.duration_ms)}</span><span class="chip">📦 ${fmtInt(c.result_chars)} chars</span><span class="chip mono">${esc(c.call_id)}</span></div>
    ${c.reasoning?.length ? `<div class="card-title" style="margin:6px 0">💭 呼び出し前の推論</div>${c.reasoning.map((r) => `<div class="reason">${reasonHtml(r)}</div>`).join("")}` : ""}
    <div class="card-title" style="margin:12px 0 6px">📥 引数</div>${jsonHtml(c.arguments ?? {})}
    <div class="card-title" style="margin:12px 0 6px">📤 返り値</div>${result}`, { wide: true });
}

// --------------------------------------------------------------- live runs
function liveCardHtml(label) {
  return `<div class="msg agent" id="live-msg"><div class="avatar">◆</div><div class="body"><div class="live">
    <div class="live-head"><span class="spinner"></span><span id="live-label">${esc(label)}</span><span class="typing" style="margin-left:auto"><i></i><i></i><i></i></span></div>
    <div class="live-log" id="live-log"></div></div></div></div>`;
}
function liveEvent(icon, html) {
  const log = $("live-log");
  if (!log) return;
  log.insertAdjacentHTML("beforeend", `<div class="ev"><span class="i">${icon}</span><div>${html}</div></div>`);
  log.scrollTop = log.scrollHeight;
  scrollBottom();
}
function setLiveLabel(text) { const el = $("live-label"); if (el) el.textContent = text; }

function streamRun(runId) {
  state.running = true;
  updateComposer();
  if (!$("live-msg")) { $("thread").insertAdjacentHTML("beforeend", liveCardHtml("エージェントが作業中…")); scrollBottom(); }
  let orderDone = false;
  const es = new EventSource(`/api/runs/${runId}/events`);
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    switch (ev.event) {
      case "llm_start": setLiveLabel(`考えています…（step ${ev.step}）`); break;
      case "llm_end":
        for (const o of ev.outputs || []) {
          if (o.type === "reasoning") (o.summary || []).forEach((t) => liveEvent("💭", `<span class="reason" style="display:block">${reasonHtml(short(t, 500))}</span>`));
          if (o.type === "function_call") liveEvent("🔧", `<span class="mono">${esc(o.name)}</span> <span class="faint mono">${esc(short(o.arguments, 90))}</span>`);
          if (o.type === "message" && o.text) liveEvent("💬", `<span class="muted">${esc(short(o.text, 160))}</span>`);
        }
        break;
      case "tool_start": setLiveLabel(`${ev.tool} を実行中…`); break;
      case "tool_end":
        liveEvent("✓", `<span class="mono">${esc(ev.tool)}</span> <span class="faint">${fmtMs(ev.duration_ms)}</span>`);
        if (ORDER_TOOLS.has(ev.tool)) orderDone = true;
        break;
      case "tool_error": liveEvent("✗", `<span class="mono">${esc(ev.tool)}</span> <span class="neg">${esc(short(ev.error, 140))}</span>`); break;
      case "approval_request": liveEvent("⏸", `<span class="mono">${esc(ev.tool)}</span> の承認を待っています`); break;
      case "approval_decision": liveEvent(ev.approved ? "✅" : "⛔", `<span class="mono">${esc(ev.tool)}</span> ${ev.approved ? "承認" : "却下"}`); break;
      case "run_done":
        es.close();
        state.running = false;
        if (ev.status === "error") toast(ev.error || "エラーが発生しました", "err", 8000);
        if (ev.status === "awaiting") toast("注文の承認が必要です", "ok");
        state.decisions = {};
        openConversation(state.convId).then(loadConversations);
        if (orderDone) loadPortfolio();
        break;
    }
  };
  es.onerror = () => { /* EventSource reconnects and resumes from Last-Event-ID */ };
}

async function send(text) {
  text = (text || "").trim();
  if (!text || state.running) return;
  if (state.data?.pending?.length) return toast("承認待ちの注文があります", "err");
  if (!state.data?.turns?.length) $("thread").innerHTML = "";
  $("thread").insertAdjacentHTML("beforeend", `<div class="msg user"><div class="bubble">${esc(text)}</div></div>` + liveCardHtml("エージェントが作業中…"));
  $("input").value = ""; autosize();
  scrollBottom();
  state.running = true; updateComposer();
  try {
    const body = { text, model: settings.model, reasoning_effort: settings.effort || null };
    const url = state.convId ? `/api/conversations/${state.convId}/messages` : "/api/conversations";
    const res = await api(url, { method: "POST", body });
    if (!state.convId) { state.convId = res.conversation_id; history.pushState(null, "", `/c/${res.conversation_id}`); loadConversations(); }
    streamRun(res.run_id);
  } catch (e) {
    state.running = false;
    toast(e.message, "err", 7000);
    $("live-msg")?.remove();
    updateComposer();
  }
}

async function submitDecisions() {
  const decisions = state.decisions;
  $("thread").querySelector(".approval")?.closest(".msg")?.remove();
  $("thread").insertAdjacentHTML("beforeend", liveCardHtml("判断をエージェントに伝えています…"));
  try {
    const res = await api(`/api/conversations/${state.convId}/approvals`, { method: "POST", body: { decisions } });
    streamRun(res.run_id);
  } catch (e) {
    toast(e.message, "err");
    state.decisions = {};
    openConversation(state.convId);
  }
}

// ----------------------------------------------------------------- composer
const input = $("input");
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 200) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); }
});
$("composer").addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
function updateComposer() {
  const pending = !!state.data?.pending?.length;
  const noKey = layout.dataset.hasKey !== "1";
  input.disabled = state.running || pending || noKey;
  $("send").disabled = input.disabled;
  input.placeholder = pending ? "承認待ちの注文があります" : state.running ? "エージェントが作業中です…" : "メッセージを入力…（Enterで送信 / Shift+Enterで改行）";
  $("composer-status").textContent = state.running ? "実行中…" : "";
  document.querySelectorAll("#quick button").forEach((b) => (b.disabled = input.disabled));
}
function scrollBottom(smooth = true) {
  const el = $("chat-scroll");
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}

// --------------------------------------------------------------- side panel
$("quick").innerHTML = QUICK.map(([i, t, p]) => `<button class="btn block" style="justify-content:flex-start" data-prompt="${esc(p)}" title="${esc(p)}">${i} ${esc(t)}</button>`).join("");
$("quick").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) send(b.dataset.prompt); });

async function loadPortfolio() {
  const box = $("portfolio");
  box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
  try {
    state.portfolio = await api("/api/portfolio");
  } catch (e) {
    box.innerHTML = `<div class="callout danger" style="font-size:12.5px">${esc(e.message)}</div>`;
    return;
  }
  const { positions, totals } = state.portfolio;
  box.innerHTML = `<div class="kpis" style="grid-template-columns:1fr 1fr;margin-bottom:10px">
      <div class="kpi"><div class="label">評価額</div><div class="value">${fmtUsd(totals.value)}</div><div class="sub">${positions.length} 銘柄</div></div>
      <div class="kpi"><div class="label">含み損益</div><div class="value ${pnlClass(totals.pnl)}">${fmtSigned(totals.pnl)}</div>
        <div class="sub">${totals.cost ? fmtPct((totals.pnl / totals.cost) * 100) : ""}</div></div></div>
    <div class="pos-list">${positions.map((p) => `<div class="pos-item">
        ${p.icon ? `<img src="${esc(p.icon)}" alt="">` : `<div class="pos-icon"></div>`}
        <div style="min-width:0"><div class="q" title="${esc(p.title)}">${esc(p.title)}</div>
          <div class="s">${esc(p.token_name)} · ${p.size.toFixed(2)} @ ${fmtPrice(p.avr_price)} → ${fmtPrice(p.price)}</div></div>
        <div class="v">${fmtUsd(p.size * p.price)}<div class="${pnlClass(p.delta)}" style="font-size:11.5px">${fmtSigned(p.delta)}</div></div></div>`).join("") ||
      `<div class="muted" style="font-size:13px">保有ポジションはありません</div>`}</div>`;
  if (state.data?.pending?.length) renderThread();
}
$("refresh-portfolio").addEventListener("click", loadPortfolio);

function renderStats() {
  const d = state.data;
  if (!d || !d.turns.length) { $("conv-stats").innerHTML = "まだメッセージがありません。"; return; }
  const steps = d.turns.flatMap((t) => t.steps);
  const tools = steps.flatMap((s) => s.tools);
  const tokens = steps.reduce((n, s) => n + (s.usage?.total_tokens || 0), 0);
  const cost = steps.reduce((n, s) => n + costUsd(s.usage), 0);
  const orders = tools.filter((c) => ORDER_TOOLS.has(c.name)).reverse();
  $("conv-stats").innerHTML = `<div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:10px">
      <div class="kpi"><div class="label">ターン</div><div class="value">${d.turns.length}</div></div>
      <div class="kpi"><div class="label">ツール</div><div class="value">${tools.length}</div></div>
      <div class="kpi" title="${fmtInt(tokens)} tokens"><div class="label">コスト</div><div class="value">${fmtUsd(cost, 3)}</div></div></div>
    ${orders.length ? `<div class="card-title" style="margin:4px 0 8px">注文履歴</div><div class="stack" style="gap:6px">${orders.map(orderCardHtml).join("")}</div>` : ""}
    <a class="btn sm block" style="margin-top:10px" href="/logs/${esc(d.session_id)}">📊 ログビューアで詳しく見る</a>`;
}

// --------------------------------------------------------------------- init
loadConversations();
loadPortfolio();
if (state.convId) openConversation(state.convId); else renderThread();
