/**
 * Backtest: avvio dal dettaglio del portafoglio automatico e schermata dei risultati.
 */
import { api } from "../api.js";
import { closeSheet, openSheet, toast } from "../app.js";
import { cls, date, esc, money, num, pct, price } from "../format.js";
import { historyChart } from "./portfolio.js";
import { strategyTitle, universeLabel } from "./auto.js";

const SIDE_LABELS = { buy: "Acquisto", sell: "Vendita", dividend: "Dividendo", stamp: "Bollo" };
const SIDE_CLS = { buy: "pos", sell: "neg", dividend: "", stamp: "muted" };
const FILTERS = { "": "Tutte", buy: "Acquisti", sell: "Vendite", dividend: "Dividendi" };
const PERIOD_LABELS ={ full: "Tutto il periodo", in_sample: "Prova", out_of_sample: "Verifica" };

// Rapporto (0,05) → testo percentuale (+5,00%)
const ratio = (v, digits = 2) => (v == null ? "—" : pct(v * 100, digits));
const plain = (v, digits = 1) => (v == null ? "—" : `${num(v * 100, digits, digits)}%`);

// ── Avvio ─────────────────────────────────────────────────────────────────────

export function openBacktestForm(cfg) {
  const year = new Date().getFullYear();
  const years = [];
  for (let y = 2006; y < year; y++) years.push(y);
  const opts = (sel) => years.map((y) => `<option value="${y}" ${y === sel ? "selected" : ""}>${y}</option>`).join("");
  const sheet = openSheet(`<h3>Backtest – ${esc(cfg.name)}</h3>
    <div class="small muted" style="margin-bottom:10px">Simula la strategia sul passato con le stesse regole, commissioni e imposte
      del portafoglio vero. Ogni acquisto e vendita avviene all'apertura del giorno dopo il segnale.</div>
    <label class="field"><span>Dal 1° gennaio del</span><select id="bt-start">${opts(2010)}</select></label>
    <label class="field" style="flex-direction:row;align-items:center;gap:8px">
      <input type="checkbox" id="bt-split-on"> <span>Dividi in prova e verifica</span></label>
    <label class="field" id="bt-split-box" style="display:none"><span>La verifica inizia il 1° gennaio del</span><select id="bt-split">${opts(2019)}</select></label>
    <div class="small muted" style="margin:-4px 0 10px">Con la divisione vedi se la strategia funziona anche negli anni che non hai usato per sceglierla.</div>
    <button class="btn primary block" id="bt-go">Avvia backtest</button><div class="error small" id="bt-err"></div>`);
  const splitOn = sheet.querySelector("#bt-split-on");
  splitOn.addEventListener("change", () => (sheet.querySelector("#bt-split-box").style.display = splitOn.checked ? "" : "none"));
  sheet.querySelector("#bt-go").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const run = await api.post(`/api/auto/${cfg.id}/backtest`, {
        start: `${sheet.querySelector("#bt-start").value}-01-01`,
        split: splitOn.checked ? `${sheet.querySelector("#bt-split").value}-01-01` : null,
      });
      closeSheet();
      location.hash = `#/backtest/${run.id}`;
    } catch (err) {
      sheet.querySelector("#bt-err").textContent = err.message;
      btn.disabled = false;
    }
  });
}

export function backtestList(runs) {
  if (!runs.length) return "";
  return `<h3 class="section-title">Backtest</h3><section class="card">
    ${runs.map((r) => `<div class="list-item clickable" data-bt="${r.id}">
      <div class="main"><div class="title">${r.start.slice(0, 4)}–${r.end.slice(0, 4)}${r.split ? ` · verifica dal ${r.split.slice(0, 4)}` : ""}</div>
        <div class="small muted">${statusText(r)}</div></div>
      <div class="right num">${r.summary ? `<span class="${cls(r.summary.cagr)}">${ratio(r.summary.cagr)}</span>
        <div class="small muted">indice ${ratio(r.summary.benchmark_cagr)}</div>` : ""}</div>
    </div>`).join("")}</section>`;
}

function statusText(r) {
  if (r.status === "done") return "rendimento annuo netto";
  if (r.status === "error") return "non riuscito";
  if (r.status === "queued") return "in coda";
  return `in corso, ${r.progress}%`;
}

// ── Risultati ─────────────────────────────────────────────────────────────────

export async function renderBacktest(el, runId) {
  let timer = null;
  const load = async () => {
    const run = await api.get(`/api/backtest/${runId}`);
    if (!el.isConnected) return;
    if (run.status === "queued" || run.status === "running") {
      el.innerHTML = progressCard(run);
      timer = setTimeout(() => load().catch(() => {}), 2000);
      return;
    }
    if (run.status === "error") {
      el.innerHTML = `${header(run)}<section class="card error">${esc(run.message || "Errore")}</section>${deleteButton()}`;
      bindDelete(el, run);
      return;
    }
    renderResults(el, run);
  };
  await load();
  return () => clearTimeout(timer);
}

function progressCard(run) {
  const label = run.status === "queued"
    ? `In coda${run.queue_position ? ` (prima ce ne sono ${run.queue_position})` : ""}…`
    : run.progress === 0 ? "Aggiornamento di indice e cambi…" : `Simulazione in corso: ${run.progress}%`;
  return `${header(run)}<section class="card">
    <div>${label}</div>
    <div class="progress"><i style="width:${run.progress}%"></i></div>
    <div class="small muted" style="margin-top:8px">Puoi uscire da questa schermata: il backtest continua sul server.</div>
  </section>`;
}

function header(run) {
  return `<section class="card">
    <h2>${esc(run.config_name || run.strategy_type)}</h2>
    <div class="small muted">${esc(strategyTitle(run.strategy_type))} · ${esc(universeLabel(run.params.universe_list))}</div>
    <div class="small muted">Dal ${date(run.start)} al ${date(run.end)} · capitale ${money(run.initial_capital, "EUR", 0)}
      ${run.split ? ` · verifica dal ${date(run.split)}` : ""}</div>
  </section>`;
}

function renderResults(el, run) {
  const r = run.results;
  const periods = Object.keys(r.periods);
  let period = "full";
  el.innerHTML = `${header(run)}
    <section class="card">
      <h2>Andamento</h2>
      ${historyChart(r.chart)}
      <div class="chart-legend">
        <span><i style="background:var(--accent, #2f6fde)"></i>Strategia</span>
        <span><i style="background:var(--muted)"></i>${esc(r.benchmark_label || "Indice")}</span>
      </div>
      <div class="small muted" style="margin-top:6px">Valore del portafoglio simulato rispetto al capitale iniziale, un punto a settimana.
        L'indice è solo prezzo (senza dividendi), convertito in euro.</div>
    </section>
    ${periods.length > 1 ? `<div class="chips">${periods.map((p) => `<button class="chip ${p === period ? "active" : ""}" data-p="${p}">${PERIOD_LABELS[p]}</button>`).join("")}</div>` : ""}
    <section class="card" id="bt-metrics"></section>
    <section class="card">${summaryBlock(r)}</section>
    <section class="card">${costsBlock(r)}</section>
    <section class="card">
      <h2>Avvisi</h2>
      ${r.warnings.map((w) => `<p class="small" style="margin:.4rem 0">⚠️ ${esc(w)}</p>`).join("")}
      <p class="small muted" style="margin:.4rem 0">Versione delle regole: ${esc(run.strategy_type)} v${esc(run.strategy_version)} ·
        eseguito il ${date(run.finished_at)}.</p>
    </section>
    <h3 class="section-title">Operazioni</h3>
    <div class="chips" id="bt-sides">${Object.entries(FILTERS).map(([s, label]) => `<button class="chip ${s === "" ? "active" : ""}" data-s="${s}">${label}</button>`).join("")}</div>
    <section class="card" id="bt-trades"><div class="empty small">Caricamento…</div></section>
    ${deleteButton()}`;

  const showMetrics = () => (el.querySelector("#bt-metrics").innerHTML = metricsBlock(r.periods[period], r.benchmark_label, period));
  showMetrics();
  el.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => {
    period = b.dataset.p;
    el.querySelectorAll("[data-p]").forEach((x) => x.classList.toggle("active", x === b));
    showMetrics();
  }));
  setupTrades(el, run.id);
  bindDelete(el, run);
}

function metricsBlock(block, benchLabel, period) {
  const s = block.strategy, b = block.benchmark || {};
  const row = (label, hint, a, c) => `<tr><td>${label}<div class="small muted">${hint}</div></td>
    <td class="num">${a}</td><td class="num">${c}</td></tr>`;
  const years = (d) => (d == null ? "—" : d >= 365 ? `${num(d / 365.25, 1, 1)} anni` : `${d} giorni`);
  return `<h2>${PERIOD_LABELS[period]}</h2>
    <div class="small muted">${date(s.start)} – ${date(s.end)}${period !== "in_sample" ? " · al netto delle imposte che pagheresti vendendo tutto alla fine" : ""}</div>
    <div class="scroll-x"><table class="data-table small" style="margin-top:6px">
      <thead><tr><th></th><th class="num">Strategia</th><th class="num">${esc(benchLabel || "Indice")}</th></tr></thead>
      <tbody>
        ${row("Rendimento annuo", "medio composto", `<b class="${cls(s.cagr)}">${ratio(s.cagr)}</b>`, ratio(b.cagr))}
        ${row("Rendimento totale", "su tutto il periodo", ratio(s.total_return, 1), ratio(b.total_return, 1))}
        ${row("Volatilità annua", "quanto oscilla il valore", plain(s.volatility), plain(b.volatility))}
        ${row("Perdita massima", "dal picco al punto più basso", `<span class="neg">${plain(s.max_drawdown)}</span>`, plain(b.max_drawdown))}
        ${row("Recupero più lungo", "tempo sotto un picco precedente", years(s.longest_drawdown_days) + (s.longest_drawdown_recovered === false ? " (non ancora)" : ""), years(b.longest_drawdown_days))}
        ${row("Indice di Sharpe", "rendimento per unità di rischio", s.sharpe == null ? "—" : num(s.sharpe, 2, 2), b.sharpe == null ? "—" : num(b.sharpe, 2, 2))}
      </tbody></table></div>
    ${s.max_drawdown_peak ? `<div class="small muted" style="margin-top:6px">Perdita massima tra il ${date(s.max_drawdown_peak)} e il ${date(s.max_drawdown_trough)}.</div>` : ""}`;
}

function summaryBlock(r) {
  return `<h2>Operatività</h2><div class="grid2">
    <div class="kv"><span class="k">Valore finale</span><span class="v">${money(r.final_value, "EUR", 0)}</span></div>
    <div class="kv"><span class="k">Se vendessi tutto (netto)</span><span class="v">${money(r.liquidation_value, "EUR", 0)}</span></div>
    <div class="kv"><span class="k">Operazioni</span><span class="v">${r.trades} (${r.buys} acquisti, ${r.sells} vendite)</span></div>
    <div class="kv"><span class="k">Vendite in utile</span><span class="v">${plain(r.win_rate, 0)}</span></div>
    <div class="kv"><span class="k">Rotazione annua</span><span class="v">${plain(r.turnover, 0)}</span></div>
    <div class="kv"><span class="k">Giorni con freno drawdown</span><span class="v">${r.days_braking}</span></div>
    <div class="kv"><span class="k">Titoli alla fine</span><span class="v">${r.positions_at_end}</span></div>
    <div class="kv"><span class="k">Ordini non eseguiti</span><span class="v">${r.dropped_orders}</span></div>
  </div>
  <div class="small muted" style="margin-top:8px">Rotazione: quota del portafoglio comprata e venduta in un anno.
    Ordini non eseguiti: soprattutto acquisti senza liquidità sufficiente, come accadrebbe dal vivo.</div>`;
}

function costsBlock(r) {
  const c = r.costs;
  const line = (k, v) => `<div class="kv"><span class="k">${k}</span><span class="v">${money(v)}</span></div>`;
  return `<h2>Costi e imposte</h2><div class="grid2">
    ${line("Commissioni", c.commissions)}
    ${line("Tobin tax", c.tobin)}
    ${line("Imposte sulle plusvalenze", c.capital_gain_tax)}
    ${line("Bollo", c.stamp)}
    ${line("Dividendi lordi", c.dividends_gross)}
    ${line("Ritenute estere", c.withholding)}
    ${line("Imposte sui dividendi", c.dividend_tax)}
  </div>`;
}

function setupTrades(el, runId) {
  const box = el.querySelector("#bt-trades");
  let side = "", offset = 0, items = [];
  const load = async (reset) => {
    if (reset) { offset = 0; items = []; }
    const res = await api.get(`/api/backtest/${runId}/trades?offset=${offset}&limit=50${side ? `&side=${side}` : ""}`);
    items = items.concat(res.items);
    offset = items.length;
    box.innerHTML = items.length ? `${items.map(tradeRow).join("")}
      ${offset < res.total ? `<button class="btn block" id="bt-more" style="margin-top:8px">Altre (${res.total - offset})</button>` : ""}`
      : '<div class="empty small">Nessuna operazione.</div>';
    box.querySelector("#bt-more")?.addEventListener("click", () => load(false).catch((e) => toast(e.message)));
  };
  el.querySelectorAll("#bt-sides [data-s]").forEach((b) => b.addEventListener("click", () => {
    side = b.dataset.s;
    el.querySelectorAll("#bt-sides [data-s]").forEach((x) => x.classList.toggle("active", x === b));
    load(true).catch((e) => toast(e.message));
  }));
  load(true).catch((e) => (box.innerHTML = `<div class="error small">${esc(e.message)}</div>`));
}

function tradeRow(t) {
  const detail = t.side === "stamp" ? "" : t.side === "dividend"
    ? `${num(t.quantity, 0)} az. × ${price(t.price, t.currency)}`
    : `${num(t.quantity, 0)} az. a ${price(t.price, t.currency)}`;
  const extra = [];
  if (Number(t.costs_eur)) extra.push(`costi ${money(t.costs_eur)}`);
  if (Number(t.tax_eur)) extra.push(`imposte ${money(t.tax_eur)}`);
  if (t.realized_eur != null) extra.push(`<span class="${cls(t.realized_eur)}">risultato ${money(t.realized_eur)}</span>`);
  return `<div class="list-item">
    <div class="main"><div class="title"><span class="${SIDE_CLS[t.side] || ""}">${SIDE_LABELS[t.side] || esc(t.side)}</span>
      ${t.symbol !== "—" ? `<span class="mono">${esc(t.symbol)}</span>` : ""}</div>
      <div class="small muted">${date(t.day)}${detail ? ` · ${detail}` : ""}</div>
      <div class="small">${esc(t.reason)}</div>
      ${extra.length ? `<div class="small muted">${extra.join(" · ")}</div>` : ""}</div>
    <div class="right num ${cls(t.cash_delta_eur)}">${money(t.cash_delta_eur)}</div>
  </div>`;
}

function deleteButton() {
  return `<button class="btn btn-muted block" id="bt-del" style="margin:12px 0 24px">Elimina questo backtest</button>`;
}

function bindDelete(el, run) {
  el.querySelector("#bt-del")?.addEventListener("click", async () => {
    if (!confirm("Eliminare questo backtest?")) return;
    try {
      await api.del(`/api/backtest/${run.id}`);
      location.hash = run.config_id ? `#/automatici/${run.config_id}` : "#/automatici";
    } catch (e) {
      toast(e.message);
    }
  });
}
