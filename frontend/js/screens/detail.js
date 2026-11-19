import { api } from "../api.js";
import { openSheet, setTitle } from "../app.js";
import { cls, esc, money, num, pct, price, priceTime, MARKET_LABELS, TYPE_LABELS } from "../format.js";
import { openOrderSheet } from "./order-sheet.js";

export async function renderDetail(el, id) {
  const d = await api.get(`/api/instruments/${id}`);
  const inst = d.instrument;
  setTitle(inst.name);
  const q = d.quote;
  const pos = d.position;
  el.innerHTML = `
    <section class="card">
      <div class="small muted">${esc(inst.symbol)}${inst.isin ? " · " + esc(inst.isin) : ""} · ${MARKET_LABELS[inst.market] || inst.market} · ${TYPE_LABELS[inst.type]}</div>
      ${q ? `
        <div class="quote-big">${price(q.price, q.currency)}</div>
        <div class="${cls(q.change_pct)}">${q.change_pct !== null ? pct(q.change_pct) + " rispetto alla chiusura precedente" : ""}</div>
        <div class="small muted">Ultimo prezzo: ${priceTime(q.price_time)} (ora di Roma)
          ${q.is_manual ? ' <span class="tag manual">prezzo manuale</span>' : " · ritardato circa 15 min"}
          ${q.stale ? ' <span class="tag stale">fonte non raggiungibile</span>' : ""}</div>
        ${inst.currency !== "EUR" ? `<div class="small muted">Cambio EUR/${inst.currency}: ${num(q.fx_market, 5)} (mercato) · ≈ ${money(Number(q.price) / Number(q.fx_market))}</div>` : ""}
      ` : `<div class="error">${esc(d.error || "Prezzo non disponibile")}</div>`}
      ${inst.data_source === "manual" ? '<button class="btn small" id="manual" style="margin-top:8px">Aggiorna prezzo manuale</button>' : ""}
    </section>
    ${inst.data_source !== "manual" ? `
    <section class="card">
      <div class="chips" id="periods">
        ${["1mo", "3mo", "6mo", "1y", "5y"].map((p) => `<button class="chip ${p === "3mo" ? "active" : ""}" data-p="${p}">${{ "1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1A", "5y": "5A" }[p]}</button>`).join("")}
      </div>
      <div id="chart"><div class="empty small">Caricamento grafico…</div></div>
    </section>` : ""}
    <section class="card">
      <h2>La mia posizione</h2>
      ${pos ? `
        <div class="row"><span class="k">Quantità</span><span class="v">${pos.quantity}</span></div>
        <div class="row"><span class="k">Prezzo medio di carico</span><span class="v">${price(pos.avg_price, inst.currency)}</span></div>
        <div class="row"><span class="k">Costo fiscale (con commissioni)</span><span class="v">${money(pos.cost_eur)}</span></div>
        ${q ? `<div class="row total"><span class="k">Controvalore</span><span class="v">${money(Number(pos.quantity) * Number(q.price) / Number(q.fx_market))}</span></div>` : ""}
      ` : '<div class="muted">Nessuna posizione su questo titolo.</div>'}
    </section>
    <div class="btn-row">
      <button class="btn buy" id="buy" ${q ? "" : "disabled"}>Compra</button>
      <button class="btn sell" id="sell" ${q && pos ? "" : "disabled"}>Vendi</button>
    </div>`;

  el.querySelector("#buy").addEventListener("click", () => openOrderSheet(inst, "buy", pos));
  el.querySelector("#sell").addEventListener("click", () => openOrderSheet(inst, "sell", pos));
  el.querySelector("#manual")?.addEventListener("click", () => manualPrice(inst));

  const chartEl = el.querySelector("#chart");
  if (chartEl) {
    const loadChart = async (period) => {
      const h = await api.get(`/api/instruments/${id}/history?period=${period}`);
      chartEl.innerHTML = sparkline(h.points);
    };
    el.querySelectorAll("#periods .chip").forEach((b) => b.addEventListener("click", () => {
      el.querySelectorAll("#periods .chip").forEach((x) => x.classList.toggle("active", x === b));
      loadChart(b.dataset.p).catch(() => {});
    }));
    loadChart("3mo").catch(() => (chartEl.innerHTML = '<div class="empty small">Grafico non disponibile</div>'));
  }
}

function sparkline(points) {
  if (points.length < 2) return '<div class="empty small">Dati storici non disponibili</div>';
  const vals = points.map((p) => Number(p.close));
  const min = Math.min(...vals), max = Math.max(...vals);
  const w = 320, h = 140, pad = 6;
  const x = (i) => pad + (i * (w - 2 * pad)) / (vals.length - 1);
  const y = (v) => h - pad - ((v - min) / (max - min || 1)) * (h - 2 * pad);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? "var(--pos)" : "var(--neg)";
  const change = (vals[vals.length - 1] / vals[0] - 1) * 100;
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Andamento del prezzo">
      <path class="line" d="${d}" stroke="${color}" vector-effect="non-scaling-stroke"/></svg>
    <div class="small muted" style="display:flex;justify-content:space-between">
      <span>min ${num(min, 3)} · max ${num(max, 3)}</span><span class="${up ? "pos" : "neg"}">${pct(change)} nel periodo</span></div>`;
}

function manualPrice(inst) {
  const sheet = openSheet(`<h3>Prezzo manuale – ${esc(inst.name)}</h3>
    <label class="field"><span>Prezzo (${inst.currency})</span><input type="text" inputmode="decimal" id="mp"></label>
    <button class="btn primary block" id="save">Salva</button><div class="error small" id="err"></div>`);
  sheet.querySelector("#save").addEventListener("click", async () => {
    try {
      await api.put(`/api/instruments/${inst.id}/manual-price`, { price: sheet.querySelector("#mp").value.replace(",", ".") });
      location.reload();
    } catch (e) { sheet.querySelector("#err").textContent = e.message; }
  });
}
