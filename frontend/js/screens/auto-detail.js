/**
 * Schermata "Dettaglio portafoglio automatico".
 * Mostra la configurazione, l'ultimo run e le decisioni.
 */
import { api } from "../api.js";
import { esc, dateTime, money } from "../format.js";
import {
  dataLine, MONTHS, paramLabel, perfHtml, pollWhilePreparing, readableParams, strategyDescription, strategyTitle,
} from "./auto.js";
import { backtestList, openBacktestForm } from "./backtest.js";

const ACTION_LABELS = { buy: "Acquisto", sell: "Vendita", hold: "Mantieni", skip: "Skip" };
const ACTION_CLS = { buy: "pos", sell: "neg", hold: "muted", skip: "muted" };

export async function renderAutoDetail(el, configId) {
  const id = parseInt(configId, 10);
  el.innerHTML = '<div class="empty">Caricamento…</div>';

  const load = async () => {
    let cfg, runs, backtests;
    try {
      [cfg, runs, backtests] = await Promise.all([
        api.get(`/api/auto/${id}`),
        api.get(`/api/auto/${id}/runs?limit=5`),
        api.get(`/api/auto/${id}/backtests`),
      ]);
    } catch (e) {
      if (el.isConnected) el.innerHTML = `<div class="card error">${esc(e.message)}</div>`;
      return;
    }
    if (!el.isConnected) return;
    el.innerHTML = headerCard(cfg) + backtestList(backtests)
      + '<h3 class="section-title">Esecuzioni</h3>' + runsSection(runs);

    el.querySelector("#btn-bt")?.addEventListener("click", () => openBacktestForm(cfg));
    el.querySelector("#btn-pause").addEventListener("click", async () => {
      try {
        await api.patch(`/api/auto/${id}/pause`);
        await load();
      } catch (err) {
        alert(err.message);
      }
    });
    bindParamEditor(el, cfg, load);
    el.querySelectorAll("[data-bt]").forEach((r) =>
      r.addEventListener("click", () => (location.hash = `#/backtest/${r.dataset.bt}`)));

    el.querySelector("#btn-dry").addEventListener("click", async () => {
      const b = el.querySelector("#btn-dry");
      b.disabled = true;
      b.textContent = "In corso…";
      try {
        await api.post(`/api/auto/${id}/run_now`);
        await load();
      } catch (err) {
        alert(err.message);
        b.disabled = false;
        b.textContent = "Prova ora (dry-run)";
      }
    });

    pollWhilePreparing(el, [cfg], load);
  };

  await load();
}

function headerCard(cfg) {
  const statusLabel = cfg.is_paused
    ? '<span class="badge badge-muted">In pausa</span>'
    : cfg.is_drawdown_braking
    ? '<span class="badge badge-warn">Freno drawdown attivo</span>'
    : '<span class="badge badge-ok">Attivo</span>';

  const paramRows = readableParams(cfg).map(([k, v]) =>
    `<div class="kv"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`
  ).join("");

  return `
    <section class="card">
      <div class="card-row">
        <h2>${esc(cfg.name)}</h2>
        ${statusLabel}
      </div>
      <div class="small muted">${esc(strategyTitle(cfg.strategy_type))}</div>
      <p class="small" style="margin-top:.4rem">${esc(strategyDescription(cfg))}</p>
      ${cfg.is_drawdown_braking ? `<p class="small" style="margin-top:.4rem"><strong>Freno drawdown:</strong> il valore del portafoglio è sceso oltre il 20% dal suo massimo, quindi non fa nuovi acquisti (può solo vendere). Si spegne quando la perdita torna sotto il 10%.</p>` : ""}
      <div class="grid2" style="margin-top:.5rem">
        ${cfg.cash_balance != null ? `<div class="kv"><span class="k">Liquidità</span><span class="v">${money(cfg.cash_balance)}</span></div>` : ""}
        <div class="kv"><span class="k">Titoli in portafoglio</span><span class="v">${cfg.positions_count}</span></div>
        <div class="kv"><span class="k">Ordini in attesa</span><span class="v">${cfg.pending_orders}</span></div>
        ${perfHtml(cfg)}
        ${paramRows}
      </div>
      ${dataLine(cfg)}
      <div class="btn-row" style="margin-top:.75rem">
        <button class="btn small" id="btn-dry">Prova ora (dry-run)</button>
        ${cfg.backtest_unavailable ? "" : '<button class="btn small" id="btn-bt">Backtest</button>'}
        <button class="btn small btn-muted" id="btn-params">Modifica parametri</button>
        <button class="btn small btn-muted" id="btn-pause">${cfg.is_paused ? "Riprendi" : "Pausa"}</button>
      </div>
      ${cfg.backtest_unavailable ? `<p class="small muted" style="margin-top:.5rem">Backtest non disponibile. ${esc(cfg.backtest_unavailable)}</p>` : ""}
      <form id="param-form" style="display:none;margin-top:.75rem">${paramFields(cfg)}</form>
    </section>`;
}

// ── Modifica dei parametri ───────────────────────────────────────────────────

const PERCENT_KEYS = new Set(["rebalance_band", "etf_share", "max_weight", "abs_threshold", "max_sector",
  "risk_per_trade", "stop_fixed_pct", "stop_trailing_pct"]);
const EXCLUDE_LABELS = { banks: "Banche", insurance: "Assicurazioni", utilities: "Utility" };
const SIZING_LABELS = { equal: "Pesi uguali", inverse_vol: "Inverso alla volatilità (60 giorni)", fixed_risk: "Rischio fisso per operazione" };
const OFF_WHEN_ZERO = new Set(["max_titles", "stop_fixed_pct", "stop_trailing_pct", "stop_atr_k", "stop_time_days"]);
// Titoletti che separano i gruppi di parametri comuni
const GROUP_BEFORE = { min_order: "Regole comuni", sizing: "Dimensionamento e limiti", stop_fixed_pct: "Stop facoltativi" };
const HELP = {
  sizing: "Inverso alla volatilità: i titoli più tranquilli pesano di più. Rischio fisso: peso = rischio ÷ distanza dallo stop, mai oltre il peso normale (serve uno stop di prezzo).",
  risk_per_trade: "Solo con il rischio fisso: quota del portafoglio che si accetta di perdere se scatta lo stop.",
  max_weight: "Vale sugli acquisti; gli ETF sono esclusi.",
  max_sector: "Vale sugli acquisti: un settore salito oltre il limite non viene venduto.",
  max_titles: "Scrivi 0 per non avere limiti.",
  stop_fixed_pct: "Vende se il prezzo scende di questa percentuale sotto il prezzo d'acquisto. 0 = disattivato.",
  stop_trailing_pct: "Vende se il prezzo scende di questa percentuale sotto il massimo raggiunto. 0 = disattivato.",
  stop_atr_k: "Vende se il prezzo scende di k volte l'ATR a 20 giorni sotto il prezzo d'acquisto. 0 = disattivato.",
  stop_time_days: "Vende dopo questo numero di giorni di borsa. 0 = disattivato.",
};

function paramFields(cfg) {
  const d = cfg.defaults || {};
  const p = { ...d, ...(cfg.params || {}) };
  const rows = Object.keys(d).map((k) => {
    const v = p[k], def = d[k];
    const hint = `<span class="small muted">predefinito: ${esc(defaultText(k, def))}${HELP[k] ? `. ${esc(HELP[k])}` : ""}</span>`;
    let input;
    if (k === "sizing") {
      input = `<select name="${k}">${Object.entries(SIZING_LABELS).map(([x, lab]) => `<option value="${x}" ${v === x ? "selected" : ""}>${lab}</option>`).join("")}</select>`;
    } else if (typeof def === "boolean") {
      input = `<label style="display:flex;gap:8px;align-items:center;font-weight:400;color:inherit">
        <input type="checkbox" name="${k}" ${v ? "checked" : ""}> attivo</label>`;
    } else if (k === "rebalance_month") {
      input = `<select name="${k}">${MONTHS.map((m, i) => `<option value="${i + 1}" ${Number(v) === i + 1 ? "selected" : ""}>${m}</option>`).join("")}</select>`;
    } else if (k === "refuge") {
      input = `<select name="${k}"><option value="bond" ${v === "bond" ? "selected" : ""}>ETF titoli di Stato</option>
        <option value="cash" ${v === "cash" ? "selected" : ""}>Liquidità</option></select>`;
    } else if (Array.isArray(def)) {
      input = Object.entries(EXCLUDE_LABELS).map(([x, lab]) => `<label style="display:flex;gap:8px;align-items:center;font-weight:400;color:inherit">
        <input type="checkbox" name="${k}" value="${x}" ${v.includes(x) ? "checked" : ""}> ${lab}</label>`).join("");
    } else if (PERCENT_KEYS.has(k)) {
      input = `<div style="display:flex;gap:6px;align-items:center"><input type="number" name="${k}" step="0.5" inputmode="decimal" value="${+(v * 100).toFixed(2)}"> %</div>`;
    } else {
      const step = k === "min_order" ? 100 : Number.isInteger(def) ? 1 : "any";
      input = `<div style="display:flex;gap:6px;align-items:center"><input type="number" name="${k}" step="${step}" inputmode="decimal" value="${v}">${k === "min_order" ? " €" : ""}</div>`;
    }
    const title = GROUP_BEFORE[k] || (k === "max_sector" && !("sizing" in d) ? "Limiti" : null);
    const group = title ? `<h4 class="small muted" style="margin:1rem 0 .4rem;text-transform:uppercase;letter-spacing:.04em">${title}</h4>` : "";
    return `${group}<div class="form-group"><label>${esc(paramLabel(k))}</label>${input}${hint}</div>`;
  });
  const sleeves = cfg.params?.sleeves;
  if (sleeves?.length) {
    rows.push(`<div class="form-group"><label>Quote delle strategie</label>
      ${sleeves.map((s, i) => `<div style="display:flex;gap:6px;align-items:center;margin-bottom:4px">
        <span style="min-width:2.5em">${esc(s.type)}</span>
        <input type="number" name="share_${i}" step="1" min="1" inputmode="decimal" value="${Math.round(s.share * 100)}"> %</div>`).join("")}
      <span class="small muted">predefinito: parti uguali. Le nuove quote valgono dal prossimo ribilanciamento annuo delle quote.</span></div>`);
  }
  return `
    <h3 class="section-title" style="margin-top:0">Parametri</h3>
    ${rows.join("")}
    <p class="small muted">Le modifiche valgono dal prossimo controllo. Il backtest usa sempre i parametri salvati.</p>
    <div class="btn-row">
      <button class="btn small" type="submit">Salva</button>
      <button class="btn small btn-muted" type="button" id="btn-reset">Ripristina default</button>
      <button class="btn small btn-muted" type="button" id="btn-cancel">Annulla</button>
    </div>`;
}

function defaultText(k, v) {
  if (typeof v === "boolean") return v ? "attivo" : "disattivo";
  if (k === "sizing") return (SIZING_LABELS[v] || v).toLowerCase();
  if (OFF_WHEN_ZERO.has(k) && !Number(v)) return k === "max_titles" ? "nessun limite" : "disattivato";
  if (k === "rebalance_month") return MONTHS[v - 1];
  if (k === "refuge") return v === "cash" ? "liquidità" : "ETF titoli di Stato";
  if (Array.isArray(v)) return v.map((x) => EXCLUDE_LABELS[x] || x).join(", ").toLowerCase();
  if (PERCENT_KEYS.has(k)) return `${String(+(v * 100).toFixed(2)).replace(".", ",")}%`;
  if (k === "min_order") return money(v, "EUR", 0);
  return String(v);
}

function bindParamEditor(el, cfg, reload) {
  const form = el.querySelector("#param-form");
  el.querySelector("#btn-params").addEventListener("click", () => {
    form.style.display = form.style.display === "none" ? "" : "none";
  });
  form.querySelector("#btn-cancel").addEventListener("click", () => (form.style.display = "none"));
  const send = async (body) => {
    try {
      await api.patch(`/api/auto/${cfg.id}/params`, body);
      await reload();
    } catch (err) {
      alert(err.message);
    }
  };
  form.querySelector("#btn-reset").addEventListener("click", () => {
    if (confirm("Ripristinare tutti i parametri predefiniti?")) send({ reset: true });
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const params = {};
    for (const [k, def] of Object.entries(cfg.defaults || {})) {
      if (typeof def === "boolean") params[k] = form.querySelector(`[name="${k}"]`).checked;
      else if (Array.isArray(def)) params[k] = [...form.querySelectorAll(`[name="${k}"]:checked`)].map((x) => x.value);
      else if (k === "refuge" || k === "sizing") params[k] = form.querySelector(`[name="${k}"]`).value;
      else {
        const raw = form.querySelector(`[name="${k}"]`).value.replace(",", ".");
        const n = Number(raw);
        if (raw === "" || Number.isNaN(n)) return alert(`Valore non valido: ${paramLabel(k)}`);
        params[k] = PERCENT_KEYS.has(k) ? n / 100 : n;
      }
    }
    const body = { params };
    const sleeves = cfg.params?.sleeves;
    if (sleeves?.length) body.sleeve_shares = sleeves.map((_, i) => Number(form.querySelector(`[name="share_${i}"]`).value));
    send(body);
  });
}

function runsSection(runs) {
  if (!runs.length) {
    return `<section class="card" id="runs-section"><p class="muted">Nessuna esecuzione registrata.</p></section>`;
  }
  return `<section id="runs-section">${runs.map(runCard).join("")}</section>`;
}

function runCard(run) {
  const dryBadge = run.is_dry_run
    ? '<span class="badge badge-muted">Dry-run</span>'
    : '<span class="badge badge-ok">Live</span>';
  const statusBadge = run.status === "ok"
    ? '<span class="badge badge-ok">OK</span>'
    : `<span class="badge badge-muted">${esc(run.status)}</span>`;

  const decisionRows = run.decisions.map((d) => `
    <tr>
      <td class="mono">${esc(d.symbol)}</td>
      <td class="${ACTION_CLS[d.action] || ''}">${ACTION_LABELS[d.action] || esc(d.action)}</td>
      <td class="small">${esc(d.reason_it)}</td>
    </tr>`).join("");

  return `
    <section class="card">
      <div class="card-row">
        <div>
          <div class="small muted">${dateTime(run.ran_at)}</div>
        </div>
        <div>${dryBadge} ${statusBadge}</div>
      </div>
      ${run.note ? `<div class="small muted" style="margin:.25rem 0">${esc(run.note)}</div>` : ""}
      ${run.decisions.length ? `
        <details>
          <summary class="small">${run.decisions.length} decisioni</summary>
          <div class="scroll-x">
            <table class="data-table small">
              <thead><tr><th>Titolo</th><th>Azione</th><th>Motivazione</th></tr></thead>
              <tbody>${decisionRows}</tbody>
            </table>
          </div>
        </details>` : ""}
    </section>`;
}
