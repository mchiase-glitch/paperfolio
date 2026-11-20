import { api } from "../api.js";
import { closeSheet, openSheet, toast } from "../app.js";
import { cls, date, dateTime, esc, instPrice, money, num, priceTime, signedMoney } from "../format.js";

export function openOrderSheet(inst, side, pos) {
  const isBuy = side === "buy";
  const isBond = inst.type === "bond";
  const lot = isBond ? Number(inst.lot_size) : 1;
  const label = isBond
    ? `Valore nominale (${inst.currency}, multipli di ${num(lot, 0)})${!isBuy && pos ? ` · posseduto ${num(pos.quantity, 0)}` : ""}`
    : `Quantità${!isBuy && pos ? ` (possedute: ${pos.quantity})` : ""}`;
  const sheet = openSheet(`
    <h3>${isBuy ? "Compra" : "Vendi"} ${esc(inst.name)}</h3>
    <label class="field"><span>${label}</span>
      <input type="number" inputmode="numeric" min="${lot}" step="${lot}" id="qty" placeholder="${isBond ? num(lot * 10, 0).replace(/\./g, "") : "0"}" autofocus></label>
    <div class="small muted">Ordine a mercato</div>
    <div id="summary"></div>
    <div class="error small" id="err"></div>
    <button class="btn ${isBuy ? "buy" : "sell"} block" id="confirm" disabled>Conferma ${isBuy ? "acquisto" : "vendita"}</button>
    <button class="btn block" id="cancel" style="margin-top:8px">Annulla</button>`);

  const qtyEl = sheet.querySelector("#qty");
  const summaryEl = sheet.querySelector("#summary");
  const errEl = sheet.querySelector("#err");
  const confirmBtn = sheet.querySelector("#confirm");
  let timer, current = null, seq = 0;
  qtyEl.focus();

  const update = async () => {
    const qty = qtyEl.value.trim();
    current = null;
    confirmBtn.disabled = true;
    errEl.textContent = "";
    if (!qty || Number(qty) <= 0) { summaryEl.innerHTML = ""; return; }
    const mine = ++seq;
    try {
      const pv = await api.post("/api/orders/preview", { instrument_id: inst.id, side, quantity: qty });
      if (mine !== seq) return;
      current = qty;
      summaryEl.innerHTML = render(pv, inst);
      confirmBtn.disabled = false;
    } catch (e) {
      if (mine !== seq) return;
      summaryEl.innerHTML = "";
      errEl.textContent = e.message;
    }
  };
  qtyEl.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(update, 350); });
  sheet.querySelector("#cancel").addEventListener("click", closeSheet);
  confirmBtn.addEventListener("click", async () => {
    if (!current) return;
    confirmBtn.disabled = true;
    try {
      const o = await api.post("/api/orders", { instrument_id: inst.id, side, quantity: current });
      closeSheet();
      toast(o.status === "executed" ? "Ordine eseguito" : "Ordine inserito: in attesa dell'apertura della borsa");
      setTimeout(() => location.reload(), 600);
    } catch (e) {
      errEl.textContent = e.message;
      confirmBtn.disabled = false;
    }
  });
}

function render(pv, inst) {
  const foreign = inst.currency !== "EUR";
  const isBuy = pv.side === "buy";
  const isBond = inst.type === "bond";
  const taxOnAccrued = Number(pv.interest_tax_eur);
  const rows = [
    ["Prezzo", `${instPrice(pv.price, inst.type, pv.price_currency)} <span class="small muted">(${priceTime(pv.price_time)})</span>${pv.is_manual ? ' <span class="tag manual">prezzo manuale</span>' : ""}`],
    foreign ? [`Controvalore in ${pv.price_currency}`, money(pv.gross_ccy, pv.price_currency)] : null,
    foreign ? ["Cambio di mercato", num(pv.fx_market, 5)] : null,
    foreign ? [`Cambio applicato (spread ${num(Number(pv.fx_spread) * 100, 3)}%)`, num(pv.fx_applied, 5)] : null,
    [isBond ? "Controvalore (corso secco)" : "Controvalore", money(pv.gross_eur)],
    isBond ? [`Rateo lordo <span class="small muted">(regolamento ${date(pv.settlement_date)})</span>`, money(pv.accrued_interest_eur)]
      : ["Rateo", '<span class="muted">non applicabile</span>'],
    isBond && taxOnAccrued ? [isBuy ? "Credito d'imposta sul rateo" : "Imposta sul rateo", money(Math.abs(taxOnAccrued))] : null,
    ["Commissione", money(pv.commission_eur)],
    ["Tobin tax", money(pv.tobin_tax_eur)],
    [isBond ? "Imposta stimata sulla plusvalenza" : "Imposta stimata", money(pv.tax_eur)],
    !isBuy && pv.realized_fiscal_eur !== null ? ["Plus/minus fiscale", `<span class="${cls(pv.realized_fiscal_eur)}">${signedMoney(pv.realized_fiscal_eur)}</span>`] : null,
  ].filter(Boolean);
  return `<div class="card" style="padding:4px 0;box-shadow:none">
      ${rows.map(([k, v]) => `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("")}
      <div class="row total"><span class="k">${isBuy ? "Importo addebitato" : "Importo accreditato"}</span><span class="v">${money(pv.net_eur)}</span></div>
    </div>
    ${pv.executes_now ? "" : `<div class="notice">${pv.market_open ? "Borsa aperta ma senza ancora un prezzo della seduta odierna" : "Borsa chiusa"}: l'ordine resterà <b>in attesa</b> e sarà eseguito al primo prezzo dopo l'apertura${pv.next_open ? ` (${dateTime(pv.next_open)})` : ""}. Potrai annullarlo dalla sezione Ordini.${isBuy ? ` Verranno prenotati <b>${money(pv.reserved_eur)}</b> (importo stimato + margine).` : ""}</div>`}`;
}
