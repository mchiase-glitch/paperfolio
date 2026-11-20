import { api } from "../api.js";
import { toast } from "../app.js";
import { cls, date, dateTime, esc, instPrice, money, qty, signedMoney } from "../format.js";

const STATUS = { pending: "In attesa", executed: "Eseguito", cancelled: "Annullato", rejected: "Rifiutato" };
let tab = "orders";

export async function renderOrders(el) {
  const draw = async () => {
    el.innerHTML = `
      <div class="segmented">
        <button data-tab="orders" class="${tab === "orders" ? "active" : ""}">Ordini</button>
        <button data-tab="movements" class="${tab === "movements" ? "active" : ""}">Movimenti</button>
      </div>
      <div id="content"><div class="empty">Caricamento…</div></div>`;
    el.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; draw(); }));
    const content = el.querySelector("#content");
    content.innerHTML = tab === "orders" ? await ordersHtml() : await movementsHtml();
    content.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Annullare l'ordine?")) return;
      try { await api.post(`/api/orders/${b.dataset.cancel}/cancel`); toast("Ordine annullato"); draw(); }
      catch (e) { toast(e.message); }
    }));
  };
  await draw();
}

async function ordersHtml() {
  const { orders } = await api.get("/api/orders");
  if (!orders.length) return '<div class="card empty">Nessun ordine</div>';
  const pending = orders.filter((o) => o.status === "pending");
  const other = orders.filter((o) => o.status !== "pending");
  const row = (o) => `
    <div class="list-item">
      <div class="main">
        <div class="title">${o.side === "buy" ? "Acquisto" : "Vendita"} ${qty(o.quantity, o.instrument_type, o.currency)} ${esc(o.name)}</div>
        <div class="small muted">Inserito ${dateTime(o.created_at)}${o.executed_at ? ` · eseguito ${dateTime(o.executed_at)}` : ""}${o.cancelled_at ? ` · annullato ${dateTime(o.cancelled_at)}` : ""}</div>
        ${o.execution ? `<div class="small">a ${instPrice(o.execution.price, o.instrument_type, o.execution.price_currency)}${Number(o.execution.accrued_interest_eur) ? ` + rateo ${money(o.execution.accrued_interest_eur)}` : ""} · netto ${money(Math.abs(Number(o.execution.cash_delta_eur)))}</div>` : ""}
        ${o.status === "pending" && o.side === "buy" ? `<div class="small muted">Liquidità prenotata ${money(o.reserved_eur)}</div>` : ""}
        ${o.note ? `<div class="small muted">${esc(o.note)}</div>` : ""}
      </div>
      <div class="right"><div class="status ${o.status}">${STATUS[o.status]}</div>
        ${o.status === "pending" ? `<button class="btn small" data-cancel="${o.id}" style="margin-top:6px">Annulla</button>` : ""}</div>
    </div>`;
  return `${pending.length ? `<h3 class="section-title">In attesa</h3><div class="card">${pending.map(row).join("")}</div>` : ""}
    ${other.length ? `<h3 class="section-title">Storico</h3><div class="card">${other.map(row).join("")}</div>` : ""}`;
}

async function movementsHtml() {
  const { movements } = await api.get("/api/movements");
  const items = movements.map((m) => `
    <div class="list-item">
      <div class="main">
        <div class="title">${esc(m.label)}${m.name ? " " + esc(m.name) : ""}</div>
        <div class="small muted">${dateTime(m.ts)}${m.quantity && (m.kind === "buy" || m.kind === "sell") ? ` · ${qty(m.quantity, m.instrument_type, m.price_currency)} a ${instPrice(m.price, m.instrument_type, m.price_currency)}` : ""}${m.description ? " · " + esc(m.description) : ""}</div>
        ${m.kind === "dividend" || m.kind === "coupon" ? `<div class="small muted">Lordo ${money(m.gross_eur)}${Number(m.withholding_eur) ? ` · ritenuta estera ${money(m.withholding_eur)}` : ""} · imposta ${money(m.tax_eur)}</div>` : ""}
        ${Number(m.accrued_interest_eur) ? `<div class="small muted">Rateo lordo ${money(m.accrued_interest_eur)} (regolamento ${date(m.settlement_date)}) · ${Number(m.interest_tax_eur) < 0 ? "credito d'imposta" : "imposta"} ${money(Math.abs(Number(m.interest_tax_eur)))}</div>` : ""}
        ${["buy", "sell", "redemption"].includes(m.kind) ? `<div class="small muted">Commissione ${money(m.commission_eur)}${Number(m.tobin_tax_eur) ? ` · Tobin ${money(m.tobin_tax_eur)}` : ""}${Number(m.tax_eur) ? ` · imposte ${money(m.tax_eur)}` : ""}${m.realized_fiscal_eur !== null ? ` · plus/minus <span class="${cls(m.realized_fiscal_eur)}">${signedMoney(m.realized_fiscal_eur)}</span>` : ""}</div>` : ""}
      </div>
      <div class="right num ${cls(m.cash_delta_eur)}">${m.kind === "split" ? "" : signedMoney(m.cash_delta_eur)}</div>
    </div>`).join("");
  return `<a class="btn block" href="/api/movements.csv" download style="margin-bottom:12px">Esporta in CSV</a>
    <div class="card">${items || '<div class="empty">Nessun movimento</div>'}</div>`;
}
