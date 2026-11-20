import { api } from "../api.js";
import { openSheet } from "../app.js";
import { esc, fromPercent, TYPE_LABELS } from "../format.js";

const ISIN_RE = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/;
let lastQuery = "", lastType = "";

export async function renderSearch(el) {
  el.innerHTML = `
    <input type="search" id="q" placeholder="Nome, ticker o ISIN" autocomplete="off" value="${esc(lastQuery)}">
    <div class="chips" id="types">
      ${[["", "Tutti"], ["stock", "Azioni"], ["etf", "ETF"], ["bond", "Obbligazioni"]].map(([v, l]) => `<button class="chip ${v === lastType ? "active" : ""}" data-t="${v}">${l}</button>`).join("")}
    </div>
    <button class="btn block" id="add-bond" style="margin-bottom:12px">+ Aggiungi un BTP o un'obbligazione</button>
    <div class="card" id="results"><div class="empty">Scrivi almeno due caratteri</div></div>
    <div class="small muted" style="margin:0 4px">Si possono negoziare azioni ed ETF armonizzati quotati in Europa (gli ETF USA non sono acquistabili da un risparmiatore italiano).
      Per BTP e obbligazioni non esiste una fonte gratuita affidabile: si inseriscono a mano con i dati del titolo (li trovi sul sito di Borsa Italiana cercando l'ISIN) e il prezzo va aggiornato a mano.
      Non trovi un'azione o un ETF? <a href="#" id="manual">Aggiungilo con prezzo manuale</a>.</div>`;
  const q = el.querySelector("#q");
  const results = el.querySelector("#results");
  let timer, seq = 0;

  const run = async () => {
    lastQuery = q.value.trim();
    if (lastQuery.length < 2) { results.innerHTML = '<div class="empty">Scrivi almeno due caratteri</div>'; return; }
    const mine = ++seq;
    results.innerHTML = '<div class="empty">Ricerca…</div>';
    try {
      const data = await api.get(`/api/instruments/search?q=${encodeURIComponent(lastQuery)}${lastType ? `&type=${lastType}` : ""}`);
      if (mine !== seq) return;
      results.innerHTML = data.results.length ? data.results.map(item).join("") : `<div class="empty">Nessun risultato${data.error ? ` (${esc(data.error)})` : ""}</div>`;
      results.querySelectorAll("[data-symbol]").forEach((row) => row.addEventListener("click", () => open(row.dataset)));
    } catch (e) {
      if (mine === seq) results.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    }
  };

  const open = async (ds) => {
    if (ds.id) { location.hash = `#/strumento/${ds.id}`; return; }
    if (ds.supported !== "true") return;
    try {
      const isin = ISIN_RE.test(lastQuery.toUpperCase()) ? lastQuery.toUpperCase() : null;
      const inst = await api.post("/api/instruments", { symbol: ds.symbol, isin });
      location.hash = `#/strumento/${inst.id}`;
    } catch (e) {
      results.insertAdjacentHTML("afterbegin", `<div class="error small">${esc(e.message)}</div>`);
    }
  };

  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 400); });
  el.querySelectorAll("#types .chip").forEach((b) => b.addEventListener("click", () => {
    lastType = b.dataset.t;
    el.querySelectorAll("#types .chip").forEach((x) => x.classList.toggle("active", x === b));
    run();
  }));
  el.querySelector("#manual").addEventListener("click", (e) => { e.preventDefault(); manualForm(); });
  el.querySelector("#add-bond").addEventListener("click", bondForm);
  if (lastQuery) run();
  q.focus();
}

function item(r) {
  const reason = r.supported ? "" : (r.reason || "non supportato");
  return `<div class="list-item clickable ${r.supported ? "" : "disabled"}" data-symbol="${esc(r.symbol)}" data-id="${r.known ? r.id : ""}" data-supported="${r.supported}">
    <div class="main"><div class="title">${esc(r.name)}</div>
      <div class="small muted">${esc(r.symbol)} · ${esc(r.exchange_label || "")}${r.isin ? " · " + esc(r.isin) : ""}</div></div>
    <div class="right"><span class="tag">${TYPE_LABELS[r.type] || r.type}</span>${reason ? `<div class="small muted">${reason}</div>` : ""}</div>
  </div>`;
}

function bondForm() {
  const sheet = openSheet(`<h3>Nuova obbligazione</h3>
    <div class="small muted" style="margin-bottom:10px">Titoli a tasso fisso o zero coupon quotati su MOT o EuroTLX. Prezzo in % del nominale, corso secco (senza rateo), sempre etichettato come "prezzo manuale".</div>
    <label class="field"><span>Nome (es. BTP 3,50% 01/03/2030)</span><input type="text" id="name"></label>
    <label class="field"><span>ISIN</span><input type="text" id="isin" maxlength="12" autocapitalize="characters"></label>
    <label class="field"><span>Tipo e tassazione</span><select id="category">
      <option value="titoli_stato_whitelist">Titolo di Stato o sovranazionale white list (12,5%)</option>
      <option value="obbligazioni_societarie">Obbligazione societaria (26%)</option></select></label>
    <div class="grid2">
      <label class="field"><span>Cedola annua lorda %</span><input type="text" inputmode="decimal" id="coupon" placeholder="3,50"></label>
      <label class="field"><span>Pagamento</span><select id="freq">
        <option value="2">Semestrale</option><option value="1">Annuale</option><option value="4">Trimestrale</option><option value="12">Mensile</option></select></label>
    </div>
    <div class="grid2">
      <label class="field"><span>Scadenza</span><input type="date" id="maturity"></label>
      <label class="field"><span>Emissione (facoltativa)</span><input type="date" id="issue"></label>
    </div>
    <div class="grid2">
      <label class="field"><span>Taglio minimo</span><input type="text" inputmode="numeric" id="lot" value="1000"></label>
      <label class="field"><span>Valuta</span><select id="currency"><option>EUR</option><option>USD</option></select></label>
    </div>
    <label class="field"><span>Calcolo dei giorni</span><select id="daycount">
      <option value="ACT/ACT">Giorni effettivi (ACT/ACT, BTP e quasi tutte)</option><option value="30/360">30/360</option></select></label>
    <label class="field"><span>Prezzo attuale (% del nominale, es. 98,75)</span><input type="text" inputmode="decimal" id="price"></label>
    <div class="small muted">Il paese dell'emittente si ricava dall'ISIN. La data di emissione serve solo se il titolo non ha ancora pagato la prima cedola.</div>
    <button class="btn primary block" id="save" style="margin-top:10px">Aggiungi</button><div class="error small" id="err"></div>`);
  sheet.querySelector("#save").addEventListener("click", async () => {
    const v = (id) => sheet.querySelector(`#${id}`).value.trim();
    const coupon = fromPercent(v("coupon") || "0");
    try {
      if (v("name").length < 2) throw new Error("Indica il nome del titolo");
      if (!ISIN_RE.test(v("isin").toUpperCase())) throw new Error("ISIN non valido: 12 caratteri, es. IT0005024234");
      if (!v("maturity")) throw new Error("Indica la data di scadenza");
      if (!(Number(v("price").replace(",", ".")) > 0)) throw new Error("Indica il prezzo in % del nominale");
      if (coupon === null) throw new Error("Cedola non valida");
      const inst = await api.post("/api/instruments/bond", {
        name: v("name"), isin: v("isin").toUpperCase(), category: v("category"), coupon_rate: coupon,
        coupon_frequency: Number(v("freq")), maturity: v("maturity"), issue_date: v("issue") || null,
        lot_size: v("lot").replace(/\./g, ""), currency: v("currency"), day_count: v("daycount"),
        price: v("price").replace(",", "."),
      });
      location.hash = `#/strumento/${inst.id}`;
    } catch (e) { sheet.querySelector("#err").textContent = e.message; }
  });
}

function manualForm() {
  const sheet = openSheet(`<h3>Strumento con prezzo manuale</h3>
    <div class="small muted" style="margin-bottom:10px">Per titoli che la fonte automatica non copre. Il prezzo andrà aggiornato a mano e sarà sempre etichettato come "prezzo manuale".</div>
    <label class="field"><span>Nome</span><input type="text" id="name"></label>
    <label class="field"><span>Codice (ticker o ISIN, univoco)</span><input type="text" id="symbol"></label>
    <label class="field"><span>ISIN (facoltativo)</span><input type="text" id="isin" maxlength="12"></label>
    <label class="field"><span>Tipo</span><select id="type"><option value="stock">Azione</option><option value="etf">ETF armonizzato</option></select></label>
    <label class="field"><span>Mercato</span><select id="market"><option value="ITA">Borsa Italiana</option><option value="EUR">Europa</option><option value="USA">USA</option></select></label>
    <label class="field"><span>Valuta</span><select id="currency"><option>EUR</option><option>USD</option></select></label>
    <label class="field"><span>Paese emittente (ISO, es. IT)</span><input type="text" id="country" maxlength="2"></label>
    <label class="field"><span>Prezzo attuale</span><input type="text" inputmode="decimal" id="price"></label>
    <button class="btn primary block" id="save">Aggiungi</button><div class="error small" id="err"></div>`);
  sheet.querySelector("#save").addEventListener("click", async () => {
    const v = (id) => sheet.querySelector(`#${id}`).value.trim();
    const market = v("market");
    try {
      const inst = await api.post("/api/instruments/manual", {
        name: v("name"), symbol: v("symbol").toUpperCase(), isin: v("isin").toUpperCase() || null, market, type: v("type"),
        exchange: { ITA: "XMIL", EUR: "XETR", USA: "XNYS" }[market], currency: v("currency"),
        country: v("country").toUpperCase() || null, price: v("price").replace(",", "."),
      });
      location.hash = `#/strumento/${inst.id}`;
    } catch (e) { sheet.querySelector("#err").textContent = e.message; }
  });
}
