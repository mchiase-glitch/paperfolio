import { api } from "../api.js";
import { date, dateTime, money } from "../format.js";

let year = null;

export async function renderFiscal(el) {
  const f = await api.get(`/api/fiscal${year ? `?year=${year}` : ""}`);
  year = f.year;
  const t = f.totals;
  const row = (k, v, extra = "") => `<div class="row ${extra}"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  el.innerHTML = `
    <div class="chips">${f.years.map((y) => `<button class="chip ${y === f.year ? "active" : ""}" data-y="${y}">${y}</button>`).join("")}</div>
    <section class="card">
      <h2>Riepilogo ${f.year}</h2>
      ${row("Plusvalenze realizzate", money(t.gains))}
      ${row("Minusvalenze realizzate", money(t.losses))}
      ${row("Minus dello zainetto utilizzate", money(t.loss_used))}
      ${row("Base imponibile", money(t.taxable))}
      ${row("Imposte su plusvalenze", money(t.tax), "total")}
      ${row("Tobin tax", money(t.tobin))}
      ${row("Imposta di bollo addebitata", money(t.stamp))}
      ${row("Commissioni", money(t.commissions))}
    </section>
    <h3 class="section-title">Imposte per categoria</h3>
    <section class="card">
      ${f.categories.length ? f.categories.map((c) => `
        <div class="list-item"><div class="main"><div class="title">${c.label}</div>
          <div class="small muted">Plus ${money(c.gains)} · minus ${money(c.losses)} · imponibile ${money(c.taxable)}</div></div>
          <div class="right num">${money(c.tax)}</div></div>`).join("") : '<div class="empty">Nessuna vendita nell\'anno</div>'}
    </section>
    <h3 class="section-title">Redditi di capitale: dividendi e distribuzioni</h3>
    <section class="card">
      ${f.capital_income.count ? `
        ${row(`Lordo incassato (${f.capital_income.count} accrediti)`, money(f.capital_income.gross))}
        ${row("Ritenute estere", money(f.capital_income.withholding))}
        ${row("Imposta italiana", money(f.capital_income.tax))}
        ${row("Netto accreditato", money(f.capital_income.net), "total")}` : '<div class="empty">Nessun dividendo nell\'anno</div>'}
      <div class="small muted" style="margin-top:8px">Redditi di capitale: tassati al 26% (sul netto della ritenuta del paese emittente per le azioni estere) e mai compensabili con lo zainetto.</div>
    </section>
    <h3 class="section-title">Redditi di capitale: interessi delle obbligazioni</h3>
    <section class="card">
      ${f.interest_income.count || Number(f.interest_income.accrued) ? `
        ${row(`Cedole lorde (${f.interest_income.count} accrediti)`, money(f.interest_income.coupons))}
        ${row("Ratei incassati meno ratei pagati", money(f.interest_income.accrued))}
        ${row("Imposta (al netto dei crediti sui ratei pagati)", money(f.interest_income.tax))}
        ${row("Interessi netti", money(f.interest_income.net), "total")}` : '<div class="empty">Nessun interesse nell\'anno</div>'}
      <div class="small muted" style="margin-top:8px">12,5% per titoli di Stato e sovranazionali white list, 26% per le obbligazioni societarie. Si tassa solo l'interesse maturato nel periodo di possesso: chi compra paga il rateo al venditore e riceve il credito d'imposta corrispondente.</div>
    </section>
    <h3 class="section-title">Zainetto fiscale</h3>
    <section class="card">
      ${row("Minus compensabili disponibili", money(f.zainetto_available), "total")}
      ${f.zainetto.map((z) => `
        <div class="list-item"><div class="main"><div class="title">${money(z.remaining)}</div>
          <div class="small muted">${z.category || ""} · realizzata il ${date(z.origin)}</div></div>
          <div class="right small ${z.expired ? "neg" : ""}">${z.expired ? "scaduta il" : "scade il"}<br>${date(z.expiry)}</div></div>`).join("")}
      <div class="small muted" style="margin-top:8px">Le minus valgono fino al 31/12 del quarto anno successivo e si usano a partire dalle più vecchie. Non compensano le plus degli ETF, che sono redditi di capitale.</div>
    </section>
    <h3 class="section-title">Imposta di bollo</h3>
    <section class="card">
      ${row(`Maturato nel ${f.stamp_duty.current_year} (stima)`, money(f.stamp_duty.estimate_current_year), "total")}
      ${f.stamp_duty.charged.map((s) => row(`Addebitato per il ${s.year}`, `${money(s.amount)} <span class="small muted">${dateTime(s.ts)}</span>`)).join("")}
      <div class="small muted" style="margin-top:8px">0,20% annuo sul controvalore di mercato, pro rata per i giorni di detenzione; addebitata in liquidità al 31/12 o al reset del portafoglio.</div>
    </section>`;
  el.querySelectorAll("[data-y]").forEach((b) => b.addEventListener("click", () => { year = Number(b.dataset.y); renderFiscal(el); }));
}
