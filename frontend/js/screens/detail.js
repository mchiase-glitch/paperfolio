import { api } from "../api.js";
import { closeSheet, openSheet, setTitle, toast } from "../app.js";
import { cls, date, esc, instPrice, money, num, pct, priceTime, qty, signedMoney, toPercent, FREQ_LABELS, MARKET_LABELS, TYPE_LABELS } from "../format.js";
import { openOrderSheet } from "./order-sheet.js";

export async function renderDetail(el, id) {
  const d = await api.get(`/api/instruments/${id}`);
  const inst = d.instrument;
  setTitle(inst.name);
  const q = d.quote;
  const pos = d.position;
  const isBond = inst.type === "bond";
  const factor = isBond ? 0.01 : 1;
  el.innerHTML = `
    <section class="card">
      <div class="small muted">${esc(inst.symbol)}${inst.isin && inst.isin !== inst.symbol ? " · " + esc(inst.isin) : ""} · ${MARKET_LABELS[inst.market] || inst.market} · ${TYPE_LABELS[inst.type]}</div>
      ${q ? `
        <div class="quote-big">${instPrice(q.price, inst.type, q.currency)}${isBond ? ' <span class="small muted">corso secco</span>' : ""}</div>
        <div class="${cls(q.change_pct)}">${q.change_pct !== null ? pct(q.change_pct) + " rispetto alla chiusura precedente" : ""}</div>
        <div class="small muted">Ultimo prezzo: ${priceTime(q.price_time)} (ora di Roma)
          ${q.is_manual ? ' <span class="tag manual">prezzo manuale</span>' : " · ritardato circa 15 min"}
          ${q.stale ? ' <span class="tag stale">fonte non raggiungibile</span>' : ""}</div>
        ${inst.currency !== "EUR" ? `<div class="small muted">Cambio EUR/${inst.currency}: ${num(q.fx_market, 5)} (mercato)${isBond ? "" : ` · ≈ ${money(Number(q.price) / Number(q.fx_market))}`}</div>` : ""}
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
    ${isBond ? bondCard(inst, d.bond, pos) : ""}
    <section class="card">
      <h2>La mia posizione</h2>
      ${pos ? `
        <div class="row"><span class="k">${isBond ? "Valore nominale" : "Quantità"}</span><span class="v">${qty(pos.quantity, inst.type, inst.currency)}</span></div>
        <div class="row"><span class="k">Prezzo medio di carico</span><span class="v">${instPrice(pos.avg_price, inst.type, inst.currency)}</span></div>
        <div class="row"><span class="k">Costo fiscale (con commissioni)</span><span class="v">${money(pos.cost_eur)}</span></div>
        ${q ? `<div class="row total"><span class="k">Controvalore${isBond ? " (corso secco)" : ""}</span><span class="v">${money(Number(pos.quantity) * Number(q.price) * factor / Number(q.fx_market))}</span></div>` : ""}
        ${isBond && d.bond && q ? `<div class="row"><span class="k">Rateo maturato</span><span class="v">${money(Number(pos.quantity) * Number(d.bond.accrued_per100) / 100 / Number(q.fx_market))}</span></div>` : ""}
      ` : '<div class="muted">Nessuna posizione su questo titolo.</div>'}
    </section>
    <div class="btn-row" style="margin-bottom:12px">
      <button class="btn buy" id="buy" ${q ? "" : "disabled"}>Compra</button>
      <button class="btn sell" id="sell" ${q && pos ? "" : "disabled"}>Vendi</button>
    </div>
    <section class="card">
      <h2>${isBond ? "Cedole e rimborso" : `${inst.type === "etf" ? "Distribuzioni" : "Dividendi"} ed eventi societari`}</h2>
      <div id="events"><div class="empty small">Caricamento…</div></div>
      ${isBond ? "" : '<button class="btn small" id="add-event" style="margin-top:8px">+ Aggiungi evento</button>'}
    </section>`;

  const eventsEl = el.querySelector("#events");
  const loadEvents = async () => {
    let { events } = await api.get(`/api/instruments/${id}/events`);
    if (isBond) {
      // Tutte le cedole registrate, ma solo le prossime tre in arrivo più il rimborso
      const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Rome" });
      const future = events.filter((e) => !e.processed && e.kind === "coupon" && e.ex_date >= today).reverse().slice(0, 3).reverse();
      events = events.filter((e) => e.processed || e.kind === "redemption" || future.includes(e));
    }
    eventsEl.innerHTML = events.length ? events.map((ev) => eventRow(ev, inst)).join("")
      : '<div class="muted small">Nessun evento dalla data del tuo primo acquisto. Gli eventi si aggiornano ogni mattina.</div>';
    eventsEl.querySelectorAll("[data-edit]").forEach((row) => row.addEventListener("click", () =>
      editEvent(events.find((e) => e.id === Number(row.dataset.edit)), inst, loadEvents)));
  };
  loadEvents().catch((e) => (eventsEl.innerHTML = `<div class="error small">${esc(e.message)}</div>`));
  el.querySelector("#add-event")?.addEventListener("click", () => addEvent(inst, loadEvents));

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

function bondCard(inst, b, pos) {
  const row = (k, v) => `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  return `<section class="card">
    <h2>Dati del titolo</h2>
    ${row("Cedola annua lorda", Number(inst.coupon_rate) ? `${num(toPercent(inst.coupon_rate), 4, 2)}% ${FREQ_LABELS[inst.coupon_frequency]}` : "zero coupon")}
    ${row("Scadenza", date(inst.maturity))}
    ${inst.issue_date ? row("Emissione", date(inst.issue_date)) : ""}
    ${row("Taglio minimo", money(inst.lot_size, inst.currency, 0))}
    ${b ? `
      ${row("Tassazione interessi e plus", `${num(toPercent(b.tax_rate), 2, 1)}% <span class="small muted">${esc(b.tax_label)}</span>`)}
      ${b.next_coupon ? row("Prossima cedola", `${date(b.next_coupon.date)} · ${num(b.next_coupon.amount, 4, 2)} ogni 100`) : ""}
      ${row(`Rateo per 100 al ${date(b.settlement_date)}`, num(b.accrued_per100, 5, 2))}
      <div class="divider"></div>
      ${row("Rendimento a scadenza lordo", b.ytm_gross !== null ? pct(toPercent(b.ytm_gross)) : "—")}
      ${row("Rendimento a scadenza netto", b.ytm_net !== null ? `<b>${pct(toPercent(b.ytm_net))}</b>` : "—")}
      <div class="small muted" style="margin-top:6px">Rendimento annuo composto al prezzo attuale più il rateo, con regolamento ${date(b.settlement_date)} (2 giorni di borsa dopo l'ordine). Il netto toglie l'imposta su cedole e scarto di prezzo; esclude commissioni e bollo.</div>` : ""}
  </section>`;
}

function eventRow(ev, inst) {
  const status = ev.processed ? '<span class="status executed">Registrato</span>' : '<span class="status pending">In arrivo</span>';
  if (ev.kind === "coupon" || ev.kind === "redemption") {
    const title = ev.kind === "coupon" ? `Cedola ${num(ev.amount, 4, 2)} ogni 100` : `Rimborso al ${num(ev.amount, 2)}%`;
    return `<div class="list-item"><div class="main"><div class="title">${title}</div>
      <div class="small muted">${ev.kind === "coupon" ? "pagamento" : "scadenza"} ${date(ev.ex_date)}</div></div>
      <div class="right">${status}${ev.net_eur !== null ? `<div class="small pos">${signedMoney(ev.net_eur)}</div>` : ""}</div></div>`;
  }
  if (ev.kind === "split") {
    return `<div class="list-item"><div class="main"><div class="title">${esc(ev.label)}</div>
      <div class="small muted">efficace dal ${date(ev.ex_date)}${ev.source === "manual" ? " · inserito a mano" : ""}</div></div>
      <div class="right">${status}</div></div>`;
  }
  return `<div class="list-item ${ev.editable ? "clickable" : ""}" ${ev.editable ? `data-edit="${ev.id}"` : ""}>
    <div class="main"><div class="title">${inst.type === "etf" ? "Distribuzione" : "Dividendo"} ${ev.amount ? `${num(ev.amount, 6)} ${inst.currency}` : "(importo non ancora noto)"}</div>
      <div class="small muted">stacco ${date(ev.ex_date)} · pagamento ${date(ev.pay_date)}${ev.pay_date_estimated ? " (stimato)" : ""}${ev.source === "manual" ? " · inserito a mano" : ""}</div>
      ${ev.editable ? '<div class="small muted">Tocca per correggere data o importo</div>' : ""}</div>
    <div class="right">${status}${ev.net_eur !== null ? `<div class="small pos">${signedMoney(ev.net_eur)}</div>` : ""}</div></div>`;
}

function addEvent(inst, reload) {
  const sheet = openSheet(`<h3>Nuovo evento – ${esc(inst.name)}</h3>
    <div class="small muted" style="margin-bottom:10px">Per eventi che la fonte automatica non riporta o riporta male.</div>
    <label class="field"><span>Tipo</span><select id="kind"><option value="dividend">${inst.type === "etf" ? "Distribuzione" : "Dividendo"}</option><option value="split">Frazionamento / raggruppamento</option></select></label>
    <label class="field"><span id="ex-label">Data di stacco</span><input type="date" id="ex"></label>
    <div id="div-fields">
      <label class="field"><span>Data di pagamento (vuota = stima automatica)</span><input type="date" id="pay"></label>
      <label class="field"><span>Importo lordo per azione (${inst.currency})</span><input type="text" inputmode="decimal" id="amount"></label>
    </div>
    <div id="split-fields" hidden>
      <div class="grid2">
        <label class="field"><span>Nuove azioni</span><input type="text" inputmode="decimal" id="new" value="2"></label>
        <label class="field"><span>ogni azioni possedute</span><input type="text" inputmode="decimal" id="old" value="1"></label>
      </div>
      <div class="small muted">Esempi: frazionamento 4×1 → 4 e 1; raggruppamento 1×10 → 1 e 10. Le frazioni vengono liquidate.</div>
    </div>
    <button class="btn primary block" id="save" style="margin-top:10px">Aggiungi</button><div class="error small" id="err"></div>`);
  const kind = sheet.querySelector("#kind");
  kind.addEventListener("change", () => {
    const split = kind.value === "split";
    sheet.querySelector("#div-fields").hidden = split;
    sheet.querySelector("#split-fields").hidden = !split;
    sheet.querySelector("#ex-label").textContent = split ? "Data di efficacia" : "Data di stacco";
  });
  sheet.querySelector("#save").addEventListener("click", async () => {
    const v = (s) => sheet.querySelector(s).value.trim().replace(",", ".");
    const body = { kind: kind.value, ex_date: v("#ex") };
    if (kind.value === "dividend") Object.assign(body, { pay_date: v("#pay") || null, amount: v("#amount") });
    else body.ratio = String(Number(v("#new")) / Number(v("#old")));
    try {
      await api.post(`/api/instruments/${inst.id}/events`, body);
      closeSheet();
      toast("Evento aggiunto");
      reload();
    } catch (e) { sheet.querySelector("#err").textContent = e.message; }
  });
}

function editEvent(ev, inst, reload) {
  const sheet = openSheet(`<h3>Correggi ${inst.type === "etf" ? "distribuzione" : "dividendo"}</h3>
    <div class="small muted" style="margin-bottom:10px">Stacco ${date(ev.ex_date)}. Le fonti gratuite spesso non danno la data di pagamento: puoi indicare quella vera.</div>
    <label class="field"><span>Data di pagamento</span><input type="date" id="pay" value="${ev.pay_date ?? ""}"></label>
    <label class="field"><span>Importo lordo per azione (${inst.currency})</span><input type="text" inputmode="decimal" id="amount" value="${ev.amount ?? ""}"></label>
    <button class="btn primary block" id="save">Salva</button><div class="error small" id="err"></div>`);
  sheet.querySelector("#save").addEventListener("click", async () => {
    const pay = sheet.querySelector("#pay").value;
    const amount = sheet.querySelector("#amount").value.trim().replace(",", ".");
    try {
      await api.put(`/api/events/${ev.id}`, { pay_date: pay || null, amount: amount || null });
      closeSheet();
      toast("Evento aggiornato");
      reload();
    } catch (e) { sheet.querySelector("#err").textContent = e.message; }
  });
}

function manualPrice(inst) {
  const sheet = openSheet(`<h3>Prezzo manuale – ${esc(inst.name)}</h3>
    <label class="field"><span>${inst.type === "bond" ? "Prezzo in % del nominale, corso secco (es. 98,75)" : `Prezzo (${inst.currency})`}</span><input type="text" inputmode="decimal" id="mp"></label>
    <button class="btn primary block" id="save">Salva</button><div class="error small" id="err"></div>`);
  sheet.querySelector("#save").addEventListener("click", async () => {
    try {
      await api.put(`/api/instruments/${inst.id}/manual-price`, { price: sheet.querySelector("#mp").value.replace(",", ".") });
      location.reload();
    } catch (e) { sheet.querySelector("#err").textContent = e.message; }
  });
}
