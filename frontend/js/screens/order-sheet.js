import { api } from "../api.js";
import { closeSheet, openSheet, toast } from "../app.js";
import { cls, date, dateTime, esc, instPrice, money, num, priceTime, signedMoney } from "../format.js";

const TYPE_HELP = {
  market: "Eseguito subito all'ultimo prezzo, oppure all'apertura se la borsa è chiusa.",
  limit: { buy: "Compra solo se il prezzo scende al limite o sotto.", sell: "Vende solo se il prezzo sale al limite o sopra." },
  stop: { buy: "Quando il prezzo sale fino alla soglia, compra al meglio.", sell: "Stop loss: quando il prezzo scende fino alla soglia, vende al meglio." },
};

export function orderTypeLabel(o, inst) {
  if (!o.order_type || o.order_type === "market") return "al meglio";
  const p = instPrice(o.trigger_price, inst?.type ?? o.instrument_type, inst?.currency ?? o.currency);
  return o.order_type === "limit" ? `limite ${p}` : `stop ${p}`;
}

function isoDate(d) {
  return d.toLocaleDateString("sv-SE", { timeZone: "Europe/Rome" });
}

export function openOrderSheet(inst, side, pos) {
  const isBuy = side === "buy";
  const isBond = inst.type === "bond";
  const lot = isBond ? Number(inst.lot_size) : 1;
  const label = isBond
    ? `Valore nominale (${inst.currency}, multipli di ${num(lot, 0)})${!isBuy && pos ? ` · posseduto ${num(pos.quantity, 0)}` : ""}`
    : `Quantità${!isBuy && pos ? ` (possedute: ${pos.quantity})` : ""}`;
  const in30 = new Date(Date.now() + 30 * 86400000);
  let type = "market";
  const sheet = openSheet(`
    <h3>${isBuy ? "Compra" : "Vendi"} ${esc(inst.name)}</h3>
    <div class="segmented" id="otype" style="margin-bottom:10px">
      <button data-t="market" class="active">Al meglio</button><button data-t="limit">Limite</button><button data-t="stop">Stop</button>
    </div>
    <label class="field"><span>${label}</span>
      <input type="number" inputmode="numeric" min="${lot}" step="${lot}" id="qty" placeholder="${isBond ? num(lot * 10, 0).replace(/\./g, "") : "0"}" autofocus></label>
    <div id="trigger-fields" hidden>
      <div class="grid2">
        <label class="field"><span id="trigger-label">Prezzo limite</span><input type="text" inputmode="decimal" id="trigger" placeholder="${isBond ? "es. 99,50" : "0,00"}"></label>
        <label class="field"><span>Valido fino al</span><input type="date" id="expires" value="${isoDate(in30)}" min="${isoDate(new Date())}"></label>
      </div>
    </div>
    <div class="small muted" id="help">${TYPE_HELP.market}</div>
    <div id="summary"></div>
    <div class="error small" id="err"></div>
    <button class="btn ${isBuy ? "buy" : "sell"} block" id="confirm" disabled>Conferma ${isBuy ? "acquisto" : "vendita"}</button>
    <button class="btn block" id="cancel" style="margin-top:8px">Annulla</button>`);

  const $ = (s) => sheet.querySelector(s);
  const qtyEl = $("#qty"), triggerEl = $("#trigger"), summaryEl = $("#summary"), errEl = $("#err"), confirmBtn = $("#confirm");
  let timer, current = null, seq = 0;
  qtyEl.focus();

  const body = () => {
    const b = { instrument_id: inst.id, side, quantity: qtyEl.value.trim(), order_type: type };
    if (type !== "market") {
      // "13,50" o "1.234,50" (forma italiana) oppure "13.50" dalla tastiera numerica
      const raw = triggerEl.value.trim();
      b.trigger_price = (raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw) || null;
      b.expires_on = $("#expires").value || null;
    }
    return b;
  };

  const update = async () => {
    const b = body();
    current = null;
    confirmBtn.disabled = true;
    errEl.textContent = "";
    if (!b.quantity || Number(b.quantity) <= 0 || (type !== "market" && !(Number(b.trigger_price) > 0))) {
      summaryEl.innerHTML = "";
      return;
    }
    const mine = ++seq;
    try {
      const pv = await api.post("/api/orders/preview", b);
      if (mine !== seq) return;
      current = b;
      summaryEl.innerHTML = render(pv, inst, b);
      confirmBtn.disabled = false;
    } catch (e) {
      if (mine !== seq) return;
      summaryEl.innerHTML = "";
      errEl.textContent = e.message;
    }
  };
  const later = () => { clearTimeout(timer); timer = setTimeout(update, 350); };
  qtyEl.addEventListener("input", later);
  triggerEl.addEventListener("input", later);
  $("#expires").addEventListener("change", later);
  sheet.querySelectorAll("#otype button").forEach((btn) => btn.addEventListener("click", () => {
    type = btn.dataset.t;
    sheet.querySelectorAll("#otype button").forEach((x) => x.classList.toggle("active", x === btn));
    $("#trigger-fields").hidden = type === "market";
    $("#trigger-label").textContent = type === "limit" ? "Prezzo limite" : "Prezzo di attivazione";
    $("#help").textContent = type === "market" ? TYPE_HELP.market : TYPE_HELP[type][side];
    if (type !== "market") triggerEl.focus();
    update();
  }));
  $("#cancel").addEventListener("click", closeSheet);
  confirmBtn.addEventListener("click", async () => {
    if (!current) return;
    confirmBtn.disabled = true;
    try {
      const o = await api.post("/api/orders", current);
      closeSheet();
      toast(o.status === "executed" ? "Ordine eseguito" : current.order_type === "market"
        ? "Ordine inserito: in attesa dell'apertura della borsa" : "Ordine inserito: in attesa del prezzo indicato");
      setTimeout(() => location.reload(), 600);
    } catch (e) {
      errEl.textContent = e.message;
      confirmBtn.disabled = false;
    }
  });
}

function render(pv, inst, req) {
  const foreign = inst.currency !== "EUR";
  const isBuy = pv.side === "buy";
  const isBond = inst.type === "bond";
  const conditional = pv.order_type !== "market";
  const taxOnAccrued = Number(pv.interest_tax_eur);
  const rows = [
    [conditional ? "Prezzo attuale" : "Prezzo", `${instPrice(pv.price, inst.type, pv.price_currency)} <span class="small muted">(${priceTime(pv.price_time)})</span>${pv.is_manual ? ' <span class="tag manual">prezzo manuale</span>' : ""}`],
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
  const reserve = isBuy ? ` Verranno prenotati <b>${money(pv.reserved_eur)}</b> (importo al prezzo ${conditional ? "indicato" : "stimato"} + margine).` : "";
  let notice = "";
  if (conditional && !pv.condition_met) {
    notice = `L'ordine resterà <b>in attesa</b> fino a quando il prezzo ${(pv.order_type === "limit") === isBuy ? "scenderà" : "salirà"} a ${instPrice(pv.trigger_price, inst.type, inst.currency)}${req.expires_on ? `, entro il ${date(req.expires_on)}` : ""}; poi sarà eseguito al prezzo di mercato del momento. Il controllo avviene ogni minuto a borsa aperta.${reserve}`;
  } else if (!pv.executes_now) {
    notice = `${pv.market_open ? "Borsa aperta ma senza ancora un prezzo della seduta odierna" : "Borsa chiusa"}: l'ordine resterà <b>in attesa</b> e sarà eseguito al primo prezzo dopo l'apertura${pv.next_open ? ` (${dateTime(pv.next_open)})` : ""}${conditional ? ", se la condizione di prezzo sarà ancora valida" : ""}. Potrai annullarlo dalla sezione Ordini.${reserve}`;
  } else if (conditional) {
    notice = "Il prezzo attuale soddisfa già la condizione: l'ordine sarà eseguito subito, al prezzo qui sopra.";
  }
  return `<div class="card" style="padding:4px 0;box-shadow:none">
      ${conditional ? `<div class="small muted" style="padding:6px 0">Stima calcolata al prezzo attuale</div>` : ""}
      ${rows.map(([k, v]) => `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("")}
      <div class="row total"><span class="k">${isBuy ? "Importo addebitato" : "Importo accreditato"}</span><span class="v">${money(pv.net_eur)}</span></div>
    </div>
    ${notice ? `<div class="notice">${notice}</div>` : ""}`;
}
