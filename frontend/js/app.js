import { renderPortfolio } from "./screens/portfolio.js";
import { renderDetail } from "./screens/detail.js";
import { renderSearch } from "./screens/search.js";
import { renderOrders } from "./screens/orders.js";
import { renderFiscal } from "./screens/fiscal.js";
import { renderSettings } from "./screens/settings.js";
import { renderAuto } from "./screens/auto.js";
import { renderAutoDetail } from "./screens/auto-detail.js";
import { renderBacktest } from "./screens/backtest.js";
import { api } from "./api.js";
import { esc, money } from "./format.js";

const view = document.getElementById("view");
const titleEl = document.getElementById("title");
const backBtn = document.getElementById("back");
let cleanup = null;

const routes = [
  { re: /^\/$/, tab: "portfolio", title: "Portafoglio", render: renderPortfolio },
  { re: /^\/strumento\/(\d+)$/, tab: "portfolio", title: "Dettaglio", render: renderDetail, back: true },
  { re: /^\/cerca$/, tab: "search", title: "Cerca", render: renderSearch },
  { re: /^\/ordini$/, tab: "orders", title: "Ordini e movimenti", render: renderOrders },
  { re: /^\/fiscale$/, tab: "fiscal", title: "Fiscale", render: renderFiscal },
  { re: /^\/impostazioni$/, tab: "settings", title: "Impostazioni", render: renderSettings },
  { re: /^\/automatici$/, tab: "auto", title: "Automatici", render: renderAuto },
  { re: /^\/automatici\/(\d+)$/, tab: "auto", title: "Portafoglio automatico", render: renderAutoDetail, back: true },
  { re: /^\/backtest\/(\d+)$/, tab: "auto", title: "Backtest", render: renderBacktest, back: true },
];

export function setTitle(t) { titleEl.textContent = t; }

async function route() {
  const path = location.hash.slice(1) || "/";
  const r = routes.find((x) => x.re.test(path)) || routes[0];
  const params = path.match(r.re)?.slice(1) ?? [];
  if (cleanup) { cleanup(); cleanup = null; }
  closeSheet();
  setTitle(r.title);
  backBtn.hidden = !r.back;
  document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === r.tab));
  view.innerHTML = '<div class="empty">Caricamento…</div>';
  window.scrollTo(0, 0);
  try {
    cleanup = (await r.render(view, ...params)) || null;
  } catch (e) {
    view.innerHTML = `<div class="card error">${e.message}</div>`;
  }
}

backBtn.addEventListener("click", () => (history.length > 1 ? history.back() : (location.hash = "#/")));
window.addEventListener("hashchange", route);

// --- Pannello dal basso e notifiche -------------------------------------------
const sheet = document.getElementById("sheet");
const backdrop = document.getElementById("sheet-backdrop");
backdrop.addEventListener("click", closeSheet);

export function openSheet(html) {
  sheet.innerHTML = `<div class="grab"></div>${html}`;
  sheet.hidden = false;
  backdrop.hidden = false;
  return sheet;
}

export function closeSheet() {
  sheet.hidden = true;
  backdrop.hidden = true;
  sheet.innerHTML = "";
}

let toastTimer;
export function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 3500);
}

// --- Portafoglio selezionato (pulsante in alto a destra) ---------------------------
const accountBtn = document.getElementById("account");

export async function refreshAccount() {
  if (!accountBtn) return;
  try {
    const { accounts } = await api.get("/api/accounts");
    const cur = accounts.find((a) => a.current);
    accountBtn.textContent = cur ? `${cur.name} ▾` : "Simulazione";
  } catch { /* il nome resta quello precedente */ }
}

accountBtn?.addEventListener("click", async () => {
  let accounts;
  try {
    ({ accounts } = await api.get("/api/accounts"));
  } catch (e) {
    toast(`Elenco dei portafogli non disponibile: ${e.message || e}`);
    return;
  }
  const s = openSheet(`<h3>Portafogli</h3>
    <div class="small muted" style="margin-bottom:8px">Ogni portafoglio ha liquidità, posizioni, ordini e fiscalità separati. Tocca per passare a un altro.</div>
    ${accounts.map((a) => `<div class="list-item clickable" data-acc="${a.id}">
      <div class="main"><div class="title">${esc(a.name)}${a.current ? ' <span class="tag">attivo</span>' : ""}</div>
        <div class="small muted">capitale iniziale ${money(a.initial_capital)}</div></div>
      <div class="right num">${money(a.total_value)}</div></div>`).join("")}
    <a class="btn block" href="#/impostazioni" style="margin-top:10px">Crea, rinomina o chiudi portafogli</a>`);
  s.querySelectorAll("[data-acc]").forEach((row) => row.addEventListener("click", async () => {
    await api.post(`/api/accounts/${row.dataset.acc}/select`);
    closeSheet();
    await refreshAccount();
    route();
  }));
  s.querySelector("a").addEventListener("click", closeSheet);
});

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

refreshAccount();
route();
