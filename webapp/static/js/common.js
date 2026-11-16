// Shared helpers for every page (ES module).

const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || "";

export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (res.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("login required"); }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

// ---------------------------------------------------------------- format
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmtInt = (n) => (n == null ? "–" : Math.round(n).toLocaleString("ja-JP"));
export const fmtUsd = (n, d = 2) => (n == null || isNaN(n) ? "–" : (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
export const fmtSigned = (n, d = 2) => (n == null ? "–" : (n >= 0 ? "+" : "-") + "$" + Math.abs(n).toFixed(d));
export const fmtPct = (n) => (n == null ? "–" : (n >= 0 ? "+" : "") + Number(n).toFixed(1) + "%");
export const fmtPrice = (p) => (p == null ? "–" : (p * 100).toFixed(1) + "¢");
export function fmtMs(ms) { if (ms == null) return "–"; return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`; }
export function fmtTime(ts) { if (!ts) return "–"; const d = new Date(ts); return d.toLocaleTimeString("ja-JP", { hour12: false }); }
export function fmtDateTime(ts) { if (!ts) return "–"; const d = new Date(ts); return d.toLocaleString("ja-JP", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
export function relTime(ts) {
  if (!ts) return "";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return "たった今"; if (s < 3600) return `${Math.floor(s / 60)}分前`;
  if (s < 86400) return `${Math.floor(s / 3600)}時間前`; return `${Math.floor(s / 86400)}日前`;
}
export function short(v, n = 80) { const t = typeof v === "string" ? v : JSON.stringify(v ?? ""); return t.length <= n ? t : t.slice(0, n - 1) + "…"; }
export const pnlClass = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "");

// --------------------------------------------------------------- markdown
export function md(text) {
  const html = window.marked ? window.marked.parse(String(text ?? ""), { gfm: true, breaks: true }) : esc(text);
  return window.DOMPurify ? window.DOMPurify.sanitize(html) : esc(text);
}
// Reasoning summaries: light Markdown (bold headings) without block layout.
export function reasonHtml(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}
export function highlight(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/[&<>"']/g, (c) => esc(c)) + ")", "gi");
  return safe.replace(re, "<mark>$1</mark>");
}

// ------------------------------------------------------------ JSON viewer
export function jsonHtml(value) {
  if (typeof value === "string") {
    try { value = JSON.parse(value); } catch (e) { return `<pre class="json">${esc(value)}</pre>`; }
  }
  const text = JSON.stringify(value, null, 2) ?? "null";
  const html = esc(text).replace(
    /(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false)\b|\bnull\b|-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi,
    (m, str, colon, bool) => {
      if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
      if (bool) return `<span class="b">${m}</span>`;
      if (m === "null") return `<span class="z">${m}</span>`;
      return `<span class="n">${m}</span>`;
    });
  return `<pre class="json">${html}</pre>`;
}

// List of flat objects -> table; otherwise JSON.
export function valueHtml(value) {
  if (Array.isArray(value) && value.length && value.every((v) => v && typeof v === "object" && !Array.isArray(v))) {
    const cols = [...new Set(value.flatMap((r) => Object.keys(r)))].slice(0, 12);
    const cell = (v) => esc(typeof v === "object" && v !== null ? short(v, 120) : short(v ?? "", 160));
    return `<div class="table-wrap"><table class="grid"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${value.map((r) => `<tr>${cols.map((c) => `<td>${cell(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <details class="plain" style="margin-top:6px"><summary>JSON</summary>${jsonHtml(value)}</details>`;
  }
  if (value === null || value === undefined) return `<span class="muted">(なし)</span>`;
  return jsonHtml(value);
}

// ----------------------------------------------------------- toast & modal
export function toast(message, kind = "ok", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = esc(message);
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

const modal = document.getElementById("modal");
export function openModal(html, { wide = false } = {}) {
  const body = document.getElementById("modal-body");
  body.innerHTML = html;
  modal.classList.toggle("wide", wide);
  if (!modal.open) modal.showModal();
  body.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
  return body;
}
export function closeModal() { if (modal?.open) modal.close(); }
modal?.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

export function confirmDialog({ title, html, okLabel = "OK", okClass = "primary" }) {
  return new Promise((resolve) => {
    const body = openModal(`<div class="modal-head"><h3>${esc(title)}</h3><button class="btn ghost icon" data-close>✕</button></div>
      ${html}<div class="modal-foot"><button class="btn" data-close>キャンセル</button><button class="btn ${okClass}" id="dlg-ok">${esc(okLabel)}</button></div>`);
    let ok = false;
    body.querySelector("#dlg-ok").addEventListener("click", () => { ok = true; closeModal(); });
    modal.addEventListener("close", () => resolve(ok), { once: true });
  });
}
export function imageModal(src, caption = "") {
  openModal(`<div class="modal-head"><h3>${esc(caption || "画像")}</h3><button class="btn ghost icon" data-close>✕</button></div>
    <img src="${esc(src)}" style="width:100%;border-radius:12px;background:#fff">`, { wide: true });
}

// ------------------------------------------------------------ token prices
const PRICE_KEY = "pa-prices";
export const DEFAULT_PRICES = { input: 1.25, cached: 0.125, output: 10.0 };
export function getPrices() {
  try { return { ...DEFAULT_PRICES, ...JSON.parse(localStorage.getItem(PRICE_KEY) || "{}") }; } catch (e) { return { ...DEFAULT_PRICES }; }
}
export function setPrices(p) { try { localStorage.setItem(PRICE_KEY, JSON.stringify(p)); } catch (e) { /* ignore */ } }
export function costUsd(usage, prices = getPrices()) {
  if (!usage) return 0;
  const cached = usage.cached_tokens || 0;
  const uncached = Math.max((usage.input_tokens || 0) - cached, 0);
  return (uncached * prices.input + cached * prices.cached + (usage.output_tokens || 0) * prices.output) / 1e6;
}

// ----------------------------------------------------------------- theme
document.getElementById("theme-toggle")?.addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme === "dark" || (root.dataset.theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("pa-theme", root.dataset.theme); } catch (e) { /* ignore */ }
  window.dispatchEvent(new Event("pa-theme"));
});
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
