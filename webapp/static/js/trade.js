import {
  api, esc, toast, openModal, closeModal, confirmDialog, jsonHtml, fmtUsd, fmtSigned, fmtPct, fmtPrice, fmtInt,
  pnlClass, cssVar,
} from "./common.js";

const $ = (id) => document.getElementById(id);
const TAGS = [["", "すべて"], ["ai", "AI"], ["technology", "テック"], ["economy", "経済"], ["finance", "金融"],
              ["trump", "Trump"], ["ukraine", "ウクライナ"], ["japan", "日本"], ["crypto", "暗号資産"]];
const state = { tag: "", event: null, market: null, outcome: null, interval: "1w", chart: null, portfolio: null };

// -------------------------------------------------------------------- tabs
$("trade-tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (!tab) return;
  document.querySelectorAll("#trade-tabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
  $("tab-buy").classList.toggle("hidden", tab.dataset.tab !== "buy");
  $("tab-hold").classList.toggle("hidden", tab.dataset.tab !== "hold");
});

// --------------------------------------------------------------- portfolio
async function loadPortfolio() {
  $("pf-kpis").innerHTML = Array(4).fill(`<div class="kpi skeleton" style="height:74px"></div>`).join("");
  try {
    state.portfolio = await api("/api/portfolio");
  } catch (e) {
    $("pf-kpis").innerHTML = `<div class="callout danger">${esc(e.message)}</div>`;
    $("positions").innerHTML = "";
    return;
  }
  const { positions, totals } = state.portfolio;
  $("pf-kpis").innerHTML = `
    <div class="kpi"><div class="label">評価額</div><div class="value">${fmtUsd(totals.value)}</div><div class="sub">${positions.length} 銘柄</div></div>
    <div class="kpi"><div class="label">取得額</div><div class="value">${fmtUsd(totals.cost)}</div></div>
    <div class="kpi"><div class="label">含み損益</div><div class="value ${pnlClass(totals.pnl)}">${fmtSigned(totals.pnl)}</div>
      <div class="sub">${totals.cost ? fmtPct((totals.pnl / totals.cost) * 100) : ""}</div></div>
    <div class="kpi"><div class="label">満期時の最大受取</div><div class="value">${fmtUsd(positions.reduce((n, p) => n + p.size, 0))}</div><div class="sub">全て的中した場合</div></div>`;
  renderPositions();
}

function renderPositions() {
  const positions = state.portfolio?.positions || [];
  if (!positions.length) { $("positions").innerHTML = `<div class="empty"><div class="big">📦</div>保有しているトークンはありません</div>`; return; }
  $("positions").innerHTML = `<div class="table-wrap" style="max-height:none"><table class="grid"><thead><tr>
      <th>マーケット</th><th>結果</th><th class="r">保有数</th><th class="r">平均</th><th class="r">現在</th>
      <th class="r">評価額</th><th class="r">損益</th><th>終了日</th><th></th></tr></thead><tbody>
    ${positions.map((p, i) => `<tr>
      <td><div style="display:flex;gap:10px;align-items:center;min-width:240px">${p.icon ? `<img src="${esc(p.icon)}" style="width:30px;height:30px;border-radius:8px">` : ""}
        <span style="font-weight:600">${esc(p.title)}</span></div></td>
      <td><span class="chip ${/^(yes)$/i.test(p.token_name) ? "green" : /^(no)$/i.test(p.token_name) ? "red" : "accent"}">${esc(p.token_name)}</span></td>
      <td class="r num">${p.size.toFixed(2)}</td><td class="r num">${fmtPrice(p.avr_price)}</td><td class="r num">${fmtPrice(p.price)}</td>
      <td class="r num">${fmtUsd(p.size * p.price)}</td>
      <td class="r num ${pnlClass(p.delta)}">${fmtSigned(p.delta)}<div style="font-size:11px">${fmtPct(p.percent_pnl)}</div></td>
      <td class="muted">${esc(p.end_date || "–")}</td>
      <td class="r"><button class="btn sm danger" data-sell="${i}">売却</button></td></tr>`).join("")}
    </tbody></table></div>`;
}
$("positions").addEventListener("click", (e) => { const b = e.target.closest("[data-sell]"); if (b) openSell(state.portfolio.positions[+b.dataset.sell]); });
$("reload-positions").addEventListener("click", loadPortfolio);

function openSell(p) {
  const body = openModal(`<div class="modal-head"><h3>売却</h3><button class="btn ghost icon" data-close>✕</button></div>
    <div style="font-weight:650;margin-bottom:4px">${esc(p.title)}</div>
    <div class="chips" style="margin-bottom:14px"><span class="chip accent">${esc(p.token_name)}</span><span class="chip">保有 ${p.size.toFixed(2)}</span>
      <span class="chip">現在 ${fmtPrice(p.price)}</span><span class="chip">平均 ${fmtPrice(p.avr_price)}</span></div>
    <label class="field"><span>売却数量（shares）</span>
      <div style="display:flex;gap:10px;align-items:center"><input type="range" id="sell-range" min="0" max="${p.size}" step="0.01" value="${p.size}">
        <input id="sell-qty" type="number" min="0.01" max="${p.size}" step="0.01" value="${p.size.toFixed(2)}" style="width:120px"></div></label>
    <div class="presets" style="margin:10px 0">${[25, 50, 75, 100].map((x) => `<button class="btn sm" data-pct="${x}">${x}%</button>`).join("")}</div>
    <div class="summary-rows"><div><span class="muted">推定受取額</span><b id="sell-proceeds"></b></div>
      <div><span class="muted">損益（推定）</span><b id="sell-pnl"></b></div></div>
    <div class="callout warn" style="margin-top:12px;font-size:12.5px">FAK 成行注文です。板の状況により一部のみ約定・価格が変動する可能性があります。</div>
    <div class="modal-foot"><button class="btn" data-close>キャンセル</button><button class="btn danger" id="sell-go">売却注文を送信</button></div>`);
  const range = body.querySelector("#sell-range"), qty = body.querySelector("#sell-qty");
  const update = (v) => {
    const n = Math.min(Math.max(+v || 0, 0), p.size);
    body.querySelector("#sell-proceeds").textContent = fmtUsd(n * p.price);
    const pnl = n * (p.price - p.avr_price);
    body.querySelector("#sell-pnl").innerHTML = `<span class="${pnlClass(pnl)}">${fmtSigned(pnl)}</span>`;
  };
  range.addEventListener("input", () => { qty.value = (+range.value).toFixed(2); update(range.value); });
  qty.addEventListener("input", () => { range.value = qty.value; update(qty.value); });
  body.querySelectorAll("[data-pct]").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.pct === "100" ? p.size : Math.floor(p.size * b.dataset.pct) / 100;
    qty.value = v.toFixed(2); range.value = v; update(v);
  }));
  update(p.size);
  body.querySelector("#sell-go").addEventListener("click", async () => {
    const shares = Math.min(+qty.value, p.size);
    if (!(shares > 0)) return toast("売却数量を指定してください", "err");
    closeModal();
    const ok = await confirmDialog({
      title: "売却注文の確認", okLabel: "発注する", okClass: "danger",
      html: `<div class="summary-rows"><div><span class="muted">マーケット</span><b>${esc(p.title)}</b></div>
        <div><span class="muted">トークン</span><b>${esc(p.token_name)}</b></div><div><span class="muted">数量</span><b>${shares.toFixed(2)} shares</b></div>
        <div><span class="muted">推定受取額</span><b>${fmtUsd(shares * p.price)}</b></div></div>`,
    });
    if (ok) placeOrder({ side: "SELL", token_id: p.token_id, shares });
  });
}

// ------------------------------------------------------------------ search
$("tags").innerHTML = TAGS.map(([v, l]) => `<button class="chip ${v === state.tag ? "accent" : ""}" data-tag="${v}" style="border:0;cursor:pointer">${esc(l)}</button>`).join("");
$("tags").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tag]");
  if (!b) return;
  state.tag = b.dataset.tag;
  $("tags").querySelectorAll("[data-tag]").forEach((x) => x.classList.toggle("accent", x === b));
  loadTrending();
});
$("search").addEventListener("submit", (e) => { e.preventDefault(); const v = $("slug").value.trim(); if (v) loadEvent(v); });

async function loadTrending() {
  $("trending").innerHTML = Array(6).fill(`<div class="skeleton" style="height:62px"></div>`).join("");
  $("trending-title").textContent = state.tag ? `注目のイベント · ${TAGS.find((t) => t[0] === state.tag)?.[1]}` : "注目のイベント";
  try {
    const { items } = await api(`/api/markets/trending${state.tag ? `?tag=${encodeURIComponent(state.tag)}` : ""}`);
    $("trending").innerHTML = items.map((ev) => `<button class="event-card" data-slug="${esc(ev.slug)}">
        ${ev.image ? `<img src="${esc(ev.image)}" alt="">` : `<div class="pos-icon"></div>`}
        <div style="min-width:0"><div class="t">${esc(ev.title)}</div><div class="m">24h $${fmtInt(ev.volume24hr)} · ${ev.markets} markets</div></div></button>`).join("")
      || `<div class="muted">イベントが見つかりません</div>`;
  } catch (e) {
    $("trending").innerHTML = `<div class="callout danger">${esc(e.message)}</div>`;
  }
}
$("trending").addEventListener("click", (e) => { const c = e.target.closest("[data-slug]"); if (c) loadEvent(c.dataset.slug); });

async function loadEvent(slug) {
  const card = $("event-card");
  card.classList.remove("hidden");
  card.innerHTML = `<div class="skeleton" style="height:180px"></div>`;
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    state.event = await api(`/api/markets/event?slug=${encodeURIComponent(slug)}`);
  } catch (e) {
    card.innerHTML = `<div class="callout danger">${esc(e.message)}</div>`;
    return;
  }
  const ev = state.event;
  $("slug").value = ev.slug;
  card.innerHTML = `<div class="event-hero" style="margin-bottom:14px">${ev.image ? `<img src="${esc(ev.image)}" alt="">` : ""}
      <div><h2 style="font-size:19px">${esc(ev.title)}</h2>
      <div class="chips" style="margin-top:4px"><span class="chip">24h $${fmtInt(ev.volume24hr)}</span><span class="chip">${ev.markets.length} markets</span>
        ${ev.end_date ? `<span class="chip">〜 ${esc(ev.end_date.slice(0, 10))}</span>` : ""}</div></div></div>
    ${ev.description ? `<details class="plain" style="margin-bottom:12px"><summary>イベントの詳細</summary><div class="muted" style="white-space:pre-wrap;font-size:13px;margin-top:6px">${esc(ev.description)}</div></details>` : ""}
    <div class="stack" style="gap:8px">${ev.markets.map((m, i) => `<div class="market-row" data-market="${i}">
        <div style="min-width:0"><div style="font-weight:600">${esc(m.question)}</div>
          <div class="muted" style="font-size:12px">24h $${fmtInt(m.volume24hr)} · 流動性 $${fmtInt(m.liquidity)}${m.end_date ? ` · 〜${esc(m.end_date.slice(0, 10))}` : ""}</div></div>
        <div class="outcome-btns">${m.outcomes.map((o, j) => `<button class="outcome-btn ${j === 0 ? "yes" : "no"}" data-outcome="${j}">${esc(o.name)} ${fmtPrice(o.price)}</button>`).join("")}</div>
      </div>`).join("") || `<div class="muted">取引可能なマーケットがありません</div>`}</div>`;
}

$("event-card").addEventListener("click", (e) => {
  const row = e.target.closest("[data-market]");
  if (!row) return;
  const btn = e.target.closest("[data-outcome]");
  selectOutcome(+row.dataset.market, btn ? +btn.dataset.outcome : 0);
});

// ------------------------------------------------------------------ ticket
function selectOutcome(mi, oi) {
  state.market = state.event.markets[mi];
  state.outcome = state.market.outcomes[oi];
  document.querySelectorAll(".market-row").forEach((r, i) => {
    r.classList.toggle("active", i === mi);
    r.querySelectorAll(".outcome-btn").forEach((b, j) => b.classList.toggle("sel", i === mi && j === oi));
  });
  renderTicket();
}

function renderTicket() {
  const m = state.market, o = state.outcome;
  $("ticket").innerHTML = `<div class="card card-pad stack" style="gap:12px">
    <div><div class="muted" style="font-size:12px">購入</div><div style="font-weight:700;line-height:1.35">${esc(m.question)}</div></div>
    <div class="seg" id="ticket-outcomes">${m.outcomes.map((x, j) => `<button class="${x === o ? "active" : ""}" data-o="${j}">${esc(x.name)} ${fmtPrice(x.price)}</button>`).join("")}</div>
    <div><div class="card-head" style="margin:0 0 4px"><span class="muted" style="font-size:12px">価格推移（${esc(o.name)}）</span>
      <div class="seg" id="interval">${["1d", "1w", "1m", "max"].map((iv) => `<button class="${iv === state.interval ? "active" : ""}" data-iv="${iv}">${iv}</button>`).join("")}</div></div>
      <div class="chart-box"><canvas id="price-chart"></canvas></div></div>
    <label class="field"><span>金額（USDC）</span><input id="amount" type="number" min="1" step="1" value="5"></label>
    <div class="presets">${[5, 10, 25, 50].map((v) => `<button class="btn sm" data-amt="${v}">$${v}</button>`).join("")}</div>
    <div class="summary-rows"><div><span class="muted">単価</span><b>${fmtPrice(o.price)}</b></div>
      <div><span class="muted">推定取得数</span><b id="est-shares"></b></div>
      <div><span class="muted">的中時の受取</span><b id="est-payout"></b></div>
      <div><span class="muted">的中時の利益</span><b id="est-profit" class="pos"></b></div></div>
    <button class="btn primary block" id="buy-go" style="height:42px">${esc(o.name)} を購入</button>
    <div class="faint" style="font-size:11.5px">FAK 成行注文。実際の約定価格は板の状況で変わります。</div></div>`;
  const amount = $("amount");
  const update = () => {
    const a = +amount.value || 0, shares = o.price ? a / o.price : 0;
    $("est-shares").textContent = `${shares.toFixed(2)} shares`;
    $("est-payout").textContent = fmtUsd(shares);
    $("est-profit").textContent = fmtSigned(shares - a);
  };
  amount.addEventListener("input", update);
  document.querySelectorAll("[data-amt]").forEach((b) => b.addEventListener("click", () => { amount.value = b.dataset.amt; update(); }));
  $("ticket-outcomes").addEventListener("click", (e) => { const b = e.target.closest("[data-o]"); if (b) selectOutcome(state.event.markets.indexOf(m), +b.dataset.o); });
  $("interval").addEventListener("click", (e) => { const b = e.target.closest("[data-iv]"); if (b) { state.interval = b.dataset.iv; renderTicket(); } });
  $("buy-go").addEventListener("click", async () => {
    const a = +amount.value;
    if (!(a >= 1)) return toast("金額は1 USDC以上を指定してください", "err");
    const ok = await confirmDialog({
      title: "購入注文の確認", okLabel: "発注する", okClass: "success",
      html: `<div class="summary-rows"><div><span class="muted">マーケット</span><b style="text-align:right;max-width:320px">${esc(m.question)}</b></div>
        <div><span class="muted">トークン</span><b>${esc(o.name)}</b></div><div><span class="muted">金額</span><b>${fmtUsd(a)}</b></div>
        <div><span class="muted">推定取得数</span><b>${(a / o.price).toFixed(2)} shares</b></div></div>`,
    });
    if (ok) placeOrder({ side: "BUY", token_id: o.token_id, amount_usd: a });
  });
  update();
  drawChart(o.token_id);
}

async function drawChart(tokenId) {
  let points = [];
  try { points = (await api(`/api/markets/history?token_id=${tokenId}&interval=${state.interval}`)).points; } catch (e) { /* empty chart */ }
  const canvas = $("price-chart");
  if (!canvas) return;
  state.chart?.destroy();
  const accent = cssVar("--accent"), grid = cssVar("--chart-grid"), muted = cssVar("--muted");
  const ctx = canvas.getContext("2d");
  const fill = ctx.createLinearGradient(0, 0, 0, 240);
  fill.addColorStop(0, accent + "55"); fill.addColorStop(1, accent + "00");
  state.chart = new Chart(canvas, {
    type: "line",
    data: { labels: points.map((p) => new Date(p.t * 1000)), datasets: [{ data: points.map((p) => p.p * 100), borderColor: accent, backgroundColor: fill, fill: true, tension: .25, pointRadius: 0, borderWidth: 2 }] },
    options: {
      maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: (it) => it[0].label && new Date(points[it[0].dataIndex].t * 1000).toLocaleString("ja-JP"), label: (it) => `${it.parsed.y.toFixed(1)}¢` } } },
      scales: {
        x: { ticks: { color: muted, maxTicksLimit: 5, callback(v, i) { const d = new Date(points[i]?.t * 1000); return isNaN(d) ? "" : state.interval === "1d" ? d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" }) : `${d.getMonth() + 1}/${d.getDate()}`; } }, grid: { display: false } },
        y: { ticks: { color: muted, callback: (v) => v + "¢" }, grid: { color: grid }, suggestedMin: 0, suggestedMax: 100 },
      },
    },
  });
}

async function placeOrder(body) {
  try {
    const res = await api("/api/orders", { method: "POST", body: { ...body, confirm: true } });
    const r = res.response || {};
    const failed = r.success === false || r.errorMsg || r.error_msg;
    toast(failed ? `注文は成立しませんでした: ${r.errorMsg || r.error_msg || ""}` : "注文を送信しました", failed ? "err" : "ok", 7000);
    openModal(`<div class="modal-head"><h3>${failed ? "⚠️ 注文結果" : "✅ 注文を送信しました"}</h3><button class="btn ghost icon" data-close>✕</button></div>${jsonHtml(r)}`);
    loadPortfolio();
  } catch (e) {
    toast(e.message, "err", 8000);
  }
}

window.addEventListener("pa-theme", () => { if (state.outcome) drawChart(state.outcome.token_id); });
loadPortfolio();
loadTrending();
