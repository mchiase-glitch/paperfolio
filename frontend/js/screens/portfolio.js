import { api } from "../api.js";
import { cls, date, dateTime, esc, instPrice, money, num, pct, priceTime, qty, signedMoney, toPercent, TYPE_LABELS } from "../format.js";

export async function renderPortfolio(el) {
  const load = async () => {
    const p = await api.get("/api/portfolio");
    el.innerHTML = summary(p) + upcoming(p) + positions(p);
    el.querySelectorAll("[data-instrument]").forEach((c) =>
      c.addEventListener("click", () => (location.hash = `#/strumento/${c.dataset.instrument}`)));
    el.querySelector("#refresh")?.addEventListener("click", () => load().catch(showError));
  };
  const showError = (e) => el.insertAdjacentHTML("afterbegin", `<div class="card error">${esc(e.message)}</div>`);
  await load();
  const timer = setInterval(() => { if (!document.hidden) load().catch(() => {}); }, 60000);
  return () => clearInterval(timer);
}

function summary(p) {
  const pl = p.pnl;
  return `
  <section class="card hero">
    <h2>Valore totale</h2>
    <div class="big num">${money(p.total_value)}</div>
    <div class="sub">Oggi <b class="${cls(pl.day)}">${signedMoney(pl.day)} (${pct(pl.day_pct)})</b></div>
    <div class="divider"></div>
    <div class="grid2">
      <div class="kv"><span class="k">Liquidità disponibile</span><span class="v">${money(p.available)}</span></div>
      <div class="kv"><span class="k">Liquidità prenotata</span><span class="v">${money(p.reserved)}</span></div>
      <div class="kv"><span class="k">Controvalore titoli</span><span class="v">${money(p.positions_value)}</span></div>
      ${Number(p.accrued_interest) ? `<div class="kv"><span class="k">Ratei maturati</span><span class="v">${money(p.accrued_interest)}</span></div>` : ""}
      <div class="kv"><span class="k">Capitale iniziale</span><span class="v">${money(p.initial_capital)}</span></div>
    </div>
  </section>
  <section class="card">
    <h2>Risultato</h2>
    <div class="grid2">
      <div class="kv"><span class="k">Totale lordo</span><span class="v ${cls(pl.total_gross)}">${signedMoney(pl.total_gross)}</span></div>
      <div class="kv"><span class="k">Totale netto</span><span class="v ${cls(pl.total_net)}">${signedMoney(pl.total_net)}</span></div>
      <div class="kv"><span class="k">Non realizzato lordo</span><span class="v ${cls(pl.unrealized_gross)}">${signedMoney(pl.unrealized_gross)}</span></div>
      <div class="kv"><span class="k">Non realizzato netto</span><span class="v ${cls(pl.unrealized_net)}">${signedMoney(pl.unrealized_net)}</span></div>
      <div class="kv"><span class="k">Realizzato lordo</span><span class="v ${cls(pl.realized_gross)}">${signedMoney(pl.realized_gross)}</span></div>
      <div class="kv"><span class="k">Realizzato netto</span><span class="v ${cls(pl.realized_net)}">${signedMoney(pl.realized_net)}</span></div>
    </div>
    <div class="divider"></div>
    <div class="small muted">Il realizzato comprende dividendi, distribuzioni, cedole e ratei incassati meno quelli pagati; il non realizzato comprende i ratei maturati. Netto = al netto di commissioni, imposte, ritenute, Tobin tax e bollo (stima bollo ${new Date().getFullYear()}: ${money(p.stamp_duty_estimate)}). Il non realizzato netto stima commissione e imposta di un'eventuale vendita, senza zainetto.</div>
  </section>
  <div class="refresh-line"><span>Aggiornato ${dateTime(p.as_of)}</span><button class="btn small" id="refresh">Aggiorna</button></div>`;
}

function upcoming(p) {
  if (!p.upcoming_dividends?.length) return "";
  return `<section class="card">
    <h2>Dividendi in arrivo</h2>
    ${p.upcoming_dividends.map((d) => `
      <div class="list-item clickable" data-instrument="${d.instrument_id}">
        <div class="main"><div class="title">${esc(d.name)}</div>
          <div class="small muted">${d.quantity} × ${num(d.amount, 6)} ${d.currency} · pagamento ${date(d.pay_date)}${d.pay_date_estimated ? " (stimato)" : ""}</div></div>
        <div class="right num pos">${signedMoney(d.net_eur)}<div class="small muted">netto stimato</div></div>
      </div>`).join("")}
  </section>`;
}

function positions(p) {
  if (!p.positions.length) {
    return `<div class="card empty">Nessuna posizione.<br><br><a class="btn primary" href="#/cerca">Cerca un titolo</a></div>`;
  }
  const groups = {};
  p.positions.forEach((x) => (groups[x.type] ??= []).push(x));
  return Object.entries(groups).map(([type, list]) => `
    <h3 class="section-title">${TYPE_LABELS[type] || type} (${list.length})</h3>
    ${list.map(card).join("")}`).join("");
}

function card(x) {
  const foreign = x.currency !== "EUR";
  if (x.error) {
    return `<article class="card position" data-instrument="${x.instrument_id}">
      <div class="head"><div><div class="name">${esc(x.name)}</div><span class="tag">${esc(x.symbol)}</span></div></div>
      <div class="error small">Prezzo non disponibile: ${esc(x.error)}</div>
      <div class="row"><span class="k">${x.type === "bond" ? "Nominale" : "Quantità"}</span><span class="v">${qty(x.quantity, x.type, x.currency)}</span></div>
      <div class="row"><span class="k">Prezzo medio di carico</span><span class="v">${instPrice(x.avg_price, x.type, x.currency)}</span></div>
    </article>`;
  }
  const bond = x.type === "bond";
  return `<article class="card position" data-instrument="${x.instrument_id}">
    <div class="head">
      <div>
        <div class="name">${esc(x.name)}</div>
        <span class="tag">${esc(x.symbol)}</span><span class="tag">${x.market}</span>${x.is_manual ? '<span class="tag manual">prezzo manuale</span>' : ""}${x.stale ? '<span class="tag stale">non aggiornato</span>' : ""}
      </div>
      <div class="pl ${cls(x.pnl_gross_eur)}">${signedMoney(x.pnl_gross_eur)}<div class="small">${pct(x.pnl_pct)}</div></div>
    </div>
    ${bond ? `<div class="small muted" style="margin-bottom:4px">Cedola ${num(toPercent(x.coupon_rate), 4, 2)}% · scadenza ${date(x.maturity)}</div>` : ""}
    <div class="row"><span class="k">${bond ? "Nominale" : "Quantità"}</span><span class="v">${qty(x.quantity, x.type, x.currency)}</span></div>
    <div class="row"><span class="k">Prezzo medio di carico</span><span class="v">${instPrice(x.avg_price, x.type, x.currency)}</span></div>
    <div class="row"><span class="k">Prezzo attuale <span class="small">(${priceTime(x.price_time)})</span></span><span class="v">${instPrice(x.price, x.type, x.currency)}</span></div>
    <div class="row"><span class="k">Variazione titolo oggi</span><span class="v ${cls(x.day_change_pct)}">${pct(x.day_change_pct)}</span></div>
    <div class="row"><span class="k">Risultato di oggi</span><span class="v ${cls(x.day_change_eur)}">${signedMoney(x.day_change_eur)}</span></div>
    ${foreign ? `<div class="row"><span class="k">Controvalore in ${x.currency}</span><span class="v">${money(x.market_value_ccy, x.currency)}</span></div>` : ""}
    <div class="row total"><span class="k">Controvalore${bond ? " (corso secco)" : ""}</span><span class="v">${money(x.market_value_eur)}</span></div>
    ${x.accrued_eur ? `<div class="row"><span class="k">Rateo maturato</span><span class="v">${money(x.accrued_eur)}</span></div>` : ""}
    <div class="row"><span class="k">Plus/minus netto stimato</span><span class="v ${cls(x.pnl_net_eur)}">${signedMoney(x.pnl_net_eur)}</span></div>
  </article>`;
}
