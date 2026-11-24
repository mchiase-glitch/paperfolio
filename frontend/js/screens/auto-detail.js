/**
 * Schermata "Dettaglio portafoglio automatico".
 * Mostra la configurazione, l'ultimo run e le decisioni.
 */
import { api } from "../api.js";
import { esc, dateTime, money } from "../format.js";
import { dataLine, pollWhilePreparing } from "./auto.js";

const ACTION_LABELS = { buy: "Acquisto", sell: "Vendita", hold: "Mantieni", skip: "Skip" };
const ACTION_CLS = { buy: "pos", sell: "neg", hold: "muted", skip: "muted" };

export async function renderAutoDetail(el, configId) {
  const id = parseInt(configId, 10);
  el.innerHTML = '<div class="empty">Caricamento…</div>';

  const load = async () => {
    let cfg, runs;
    try {
      [cfg, runs] = await Promise.all([
        api.get(`/api/auto/${id}`),
        api.get(`/api/auto/${id}/runs?limit=5`),
      ]);
    } catch (e) {
      if (el.isConnected) el.innerHTML = `<div class="card error">${esc(e.message)}</div>`;
      return;
    }
    if (!el.isConnected) return;
    el.innerHTML = headerCard(cfg) + runsSection(runs);

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

  const params = cfg.params || {};
  const paramRows = Object.entries(params).map(([k, v]) =>
    `<div class="kv"><span class="k">${esc(k)}</span><span class="v">${esc(String(v))}</span></div>`
  ).join("");

  return `
    <section class="card">
      <div class="card-row">
        <h2>${esc(cfg.name)}</h2>
        ${statusLabel}
      </div>
      <div class="grid2" style="margin-top:.5rem">
        <div class="kv"><span class="k">Strategia</span><span class="v">${esc(cfg.strategy_type)}</span></div>
        ${cfg.cash_balance != null ? `<div class="kv"><span class="k">Liquidità</span><span class="v">${money(cfg.cash_balance)}</span></div>` : ""}
        <div class="kv"><span class="k">Titoli in portafoglio</span><span class="v">${cfg.positions_count}</span></div>
        <div class="kv"><span class="k">Ordini in attesa</span><span class="v">${cfg.pending_orders}</span></div>
        ${paramRows}
      </div>
      ${dataLine(cfg)}
      <div class="btn-row" style="margin-top:.75rem">
        <button class="btn small" id="btn-dry">Prova ora (dry-run)</button>
      </div>
    </section>`;
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
