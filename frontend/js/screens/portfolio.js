import { api } from "../api.js";
import { cls, date, dateTime, esc, instPrice, money, num, pct, priceTime, qty, signedMoney, toPercent, TYPE_LABELS } from "../format.js";

export async function renderPortfolio(el) {
  const load = async () => {
    const p = await api.get("/api/portfolio");
    el.innerHTML = summary(p) + '<section class="card" id="history"></section>' + upcoming(p) + positions(p)
      + '<div id="watchlist"></div>';
    el.querySelectorAll("[data-instrument]").forEach((c) =>
      c.addEventListener("click", () => (location.hash = `#/strumento/${c.dataset.instrument}`)));
    el.querySelector("#refresh")?.addEventListener("click", () => load().catch(showError));
    loadHistory(el.querySelector("#history")).catch(() => {});
    loadWatchlist(el.querySelector("#watchlist")).catch(() => {});
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

// --- Andamento del portafoglio confrontato con un indice ------------------------------
function savedBenchmark() {
  try { return localStorage.getItem("benchmark") || "FTSEMIB.MI"; } catch { return "FTSEMIB.MI"; }
}

async function loadHistory(box, benchmark = savedBenchmark()) {
  const h = await api.get(`/api/portfolio/history?benchmark=${encodeURIComponent(benchmark)}`);
  const label = h.benchmarks.find((b) => b.symbol === benchmark)?.label || benchmark;
  const last = h.points[h.points.length - 1];
  box.innerHTML = `
    <h2>Andamento</h2>
    <div class="chips">${h.benchmarks.map((b) => `<button class="chip ${b.symbol === benchmark ? "active" : ""}" data-b="${esc(b.symbol)}">${esc(b.label)}</button>`).join("")}</div>
    ${historyChart(h.points)}
    <div class="chart-legend">
      <span><i style="background:var(--accent, #2f6fde)"></i>Portafoglio <b class="${cls(last.pct)}">${pct(last.pct)}</b></span>
      <span><i style="background:var(--muted)"></i>${esc(label)} <b class="${cls(last.bench_pct)}">${last.bench_pct != null ? pct(last.bench_pct) : "—"}</b></span>
    </div>
    <div class="small muted" style="margin-top:6px">Rendimento dal ${date(h.points[0].date)} rispetto al capitale iniziale, al lordo delle imposte non ancora pagate. Per l'indice conta solo il prezzo, senza dividendi.
      Ci sono solo i giorni in cui l'app era accesa (valutazione delle 23:00).${h.error ? ` ${esc(h.error)}` : ""}</div>`;
  box.querySelectorAll("[data-b]").forEach((b) => b.addEventListener("click", () => {
    try { localStorage.setItem("benchmark", b.dataset.b); } catch { /* preferenza non salvata */ }
    loadHistory(box, b.dataset.b).catch(() => {});
  }));
}

export function historyChart(points) {
  if (points.length < 2) {
    return '<div class="empty small">Il grafico si riempie con il passare dei giorni: ogni sera alle 23:00 viene salvato il valore del portafoglio.</div>';
  }
  const t = (d) => new Date(d).getTime();
  const x0 = t(points[0].date), x1 = t(points[points.length - 1].date);
  const series = [points.map((p) => [t(p.date), Number(p.pct)]),
    points.filter((p) => p.bench_pct != null).map((p) => [t(p.date), Number(p.bench_pct)])];
  const vals = series.flat().map(([, v]) => v).concat(0);
  const min = Math.min(...vals), max = Math.max(...vals);
  const w = 320, h = 150, pad = 6;
  const x = (v) => pad + ((v - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const y = (v) => h - pad - ((v - min) / (max - min || 1)) * (h - 2 * pad);
  const path = (s) => s.map(([a, b], i) => `${i ? "L" : "M"}${x(a).toFixed(1)},${y(b).toFixed(1)}`).join(" ");
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Rendimento del portafoglio e dell'indice">
      <line class="zero" x1="0" x2="${w}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/>
      ${series[1].length > 1 ? `<path class="bench" d="${path(series[1])}" vector-effect="non-scaling-stroke"/>` : ""}
      <path class="line" d="${path(series[0])}" stroke="var(--accent, #2f6fde)" vector-effect="non-scaling-stroke"/>
    </svg>
    <div class="small muted" style="display:flex;justify-content:space-between"><span>${date(points[0].date)}</span><span>min ${pct(min)} · max ${pct(max)}</span><span>${date(points[points.length - 1].date)}</span></div>`;
}

// --- Watchlist ------------------------------------------------------------------------
async function loadWatchlist(box) {
  const { items } = await api.get("/api/watchlist");
  box.innerHTML = `<h3 class="section-title">Titoli seguiti (${items.length})</h3>
    <section class="card">
      ${items.length ? items.map((w) => `
        <div class="list-item clickable" data-w="${w.instrument_id}">
          <div class="main"><div class="title">${esc(w.name)}</div>
            <div class="small muted">${esc(w.symbol)} · ${w.price_time ? priceTime(w.price_time) : ""}${w.is_manual ? " · prezzo manuale" : ""}</div></div>
          <div class="right num">${w.error ? '<span class="small muted">n.d.</span>' : instPrice(w.price, w.type, w.currency)}
            <div class="small ${cls(w.change_pct)}">${w.change_pct != null ? pct(w.change_pct) : ""}</div></div>
        </div>`).join("") : '<div class="empty small">Tocca la stella ☆ nel dettaglio di un titolo per seguirlo qui senza comprarlo.</div>'}
    </section>`;
  box.querySelectorAll("[data-w]").forEach((r) => r.addEventListener("click", () => (location.hash = `#/strumento/${r.dataset.w}`)));
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
