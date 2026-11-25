/**
 * Schermata "Automatici" – lista dei portafogli a gestione automatica.
 */
import { api } from "../api.js";
import { esc, money } from "../format.js";

export async function renderAuto(el) {
  const load = async () => {
    let configs;
    try {
      configs = await api.get("/api/auto");
    } catch (e) {
      if (!el.isConnected) return;
      el.innerHTML = `<div class="card error">${esc(e.message)}</div>`;
      return;
    }

    if (!el.isConnected) return;
    el.innerHTML = `
      <section class="card">
        <div class="card-row">
          <div>
            <h2>Portafogli automatici</h2>
            <p class="small muted">Strategie a regole fisse che operano in autonomia sui mercati.</p>
          </div>
          <button class="btn small" id="btn-new-auto">+ Nuova</button>
        </div>
      </section>
      ${configs.length
        ? configs.map(configCard).join("")
        : `<section class="card">
             <p class="muted" style="text-align:center;padding:2rem 1rem">
               Nessun portafoglio automatico configurato.<br>
               <span class="small">Premi "+ Nuova" per crearne uno.</span>
             </p>
           </section>`
      }`;

    el.querySelector("#btn-new-auto").addEventListener("click", () => openNewForm(load));

    el.querySelectorAll("[data-auto-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        location.hash = `#/automatici/${btn.dataset.autoId}`;
      });
    });

    el.querySelectorAll("[data-pause-id]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.pauseId;
        try {
          await api.patch(`/api/auto/${id}/pause`);
          await load(); // ricarica tutta la lista per aggiornare badge e pulsante
        } catch (err) {
          alert(err.message);
        }
      });
    });

    el.querySelectorAll("[data-dry-id]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.dryId;
        btn.disabled = true;
        btn.textContent = "In corso…";
        try {
          await api.post(`/api/auto/${id}/run_now`);
          location.hash = `#/automatici/${id}`;
        } catch (err) {
          alert(err.message);
        } finally {
          btn.disabled = false;
          btn.textContent = "Prova ora";
        }
      });
    });

    pollWhilePreparing(el, configs, load);
  };

  await load();
}

// Ricarica la vista finché c'è un download di dati in corso
export function pollWhilePreparing(el, configs, reload) {
  if (!configs.some((c) => c.preparation?.running)) return;
  const screen = location.hash;  // se nel frattempo si è cambiata schermata, non si ricarica
  setTimeout(() => { if (el.isConnected && location.hash === screen) reload(); }, 8000);
}

// ── Form "Nuova strategia" ────────────────────────────────────────────────────

async function openNewForm(onSuccess) {
  // Carica lista universi
  let universiList = [];
  try {
    universiList = await api.get("/api/universes");
  } catch (_) {}

  const universiOptions = universiList.map(
    (u) => `<option value="${esc(u.name)}">${esc(u.label || u.name)}</option>`
  ).join("");

  const sheet = document.createElement("div");
  sheet.className = "sheet-overlay";
  sheet.innerHTML = `
    <div class="sheet">
      <div class="sheet-header">
        <h2>Nuova strategia automatica</h2>
        <button class="btn-icon sheet-close" aria-label="Chiudi">✕</button>
      </div>
      <form id="form-new-auto" class="sheet-body">
        <div class="form-group">
          <label>Nome portafoglio</label>
          <input type="text" name="name" required placeholder="Es. P1 FTSE MIB" maxlength="100">
        </div>
        <div class="form-group">
          <label>Tipo strategia</label>
          <select name="strategy_type" id="sel-strategy-type" required>
            ${Object.entries(STRATEGY_TITLES).map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join("")}
          </select>
          <p class="small muted" id="strategy-desc" style="margin:.3rem 0 0"></p>
        </div>
        <div class="form-group" id="universe-box">
          <label id="universe-label">Lista universo</label>
          <select name="universe_list">
            ${universiOptions || '<option value="">Nessun universo disponibile</option>'}
          </select>
        </div>
        <div class="form-group">
          <label>Capitale iniziale (€)</label>
          <input type="number" name="initial_capital" required min="1000" step="100" value="100000">
        </div>
        <div id="params-p1">
          <div class="form-group">
            <label>Tolleranza prima di ribilanciare (0.25 = 25%)</label>
            <input type="number" name="rebalance_band" min="0.05" max="0.5" step="0.05" value="0.25">
          </div>
        </div>
        <div id="params-p2" style="display:none">
          <div class="form-group">
            <label>Mesi della media (di solito 10)</label>
            <input type="number" name="sma_months" min="3" max="24" step="1" value="10">
          </div>
        </div>
        <div id="params-p3" style="display:none">
          <div class="form-group">
            <label>Quota in ETF (0.5 = 50%; 1 = solo ETF, 0 = solo azioni)</label>
            <input type="number" name="etf_share" min="0" max="1" step="0.1" value="0.5">
          </div>
          <div class="form-group">
            <label>Rifugio quando nessuna regione sale</label>
            <select name="refuge"><option value="bond">ETF di titoli di Stato in euro</option><option value="cash">Liquidità</option></select>
          </div>
        </div>
        <div id="params-p4" style="display:none">
          <div class="form-group">
            <label>Titoli in portafoglio</label>
            <input type="number" name="n_hold" min="3" max="30" step="1" value="10">
          </div>
          <div class="form-group">
            <label>Si tengono finché sono tra i primi</label>
            <input type="number" name="keep_rank" min="3" max="60" step="1" value="20">
          </div>
        </div>
        <div id="params-p6" style="display:none">
          <div class="form-group">
            <label>Titoli in portafoglio</label>
            <input type="number" name="p6_n_hold" min="5" max="40" step="1" value="15">
          </div>
          <div class="form-group">
            <label>Mese della revisione annuale</label>
            <select name="rebalance_month">${MONTHS.map((m, i) => `<option value="${i + 1}" ${i === 3 ? "selected" : ""}>${m}</option>`).join("")}</select>
          </div>
        </div>
        <div id="params-p7" style="display:none">
          <div class="form-group">
            <label>Strategie da combinare (quote uguali)</label>
            ${["P1", "P2", "P3", "P4", "P5", "P6"].map((t) => `<label style="display:flex;gap:8px;align-items:center;font-weight:400;color:inherit">
              <input type="checkbox" name="sleeve" value="${t}" ${["P2", "P4", "P5"].includes(t) ? "checked" : ""}> ${esc(STRATEGY_TITLES[t])}</label>`).join("")}
          </div>
        </div>
        <div id="params-p5" style="display:none">
          <div class="form-group">
            <label>Posizioni al massimo</label>
            <input type="number" name="max_positions" min="1" max="20" step="1" value="5">
          </div>
          <div class="form-group">
            <label>Vende al più tardi dopo (giorni di borsa)</label>
            <input type="number" name="max_days" min="2" max="40" step="1" value="10">
          </div>
        </div>
        <div class="btn-row" style="margin-top:1rem">
          <button type="submit" class="btn" id="btn-submit-auto">Crea portafoglio</button>
          <button type="button" class="btn btn-muted sheet-close">Annulla</button>
        </div>
        <p id="form-error" class="small" style="color:var(--danger,#c00);display:none;margin-top:.5rem"></p>
      </form>
    </div>`;

  document.body.appendChild(sheet);

  // Toggle parametri per tipo
  const selType = sheet.querySelector("#sel-strategy-type");
  const sync = () => {
    const t = selType.value;
    for (const k of Object.keys(STRATEGY_TITLES)) {
      const box = sheet.querySelector(`#params-${k.toLowerCase()}`);
      if (box) box.style.display = k === t ? "" : "none";
    }
    sheet.querySelector("#universe-box").style.display = MULTI_LIST.includes(t) && t !== "P7" ? "none" : "";
    sheet.querySelector("#universe-label").textContent = t === "P7" ? "Lista per P1 e P2 (se scelte)" : "Lista universo";
    sheet.querySelector("#strategy-desc").textContent = strategyDescription({ strategy_type: t, params: {} })
      + (MULTI_LIST.includes(t) && t !== "P7" ? " Lavora su FTSE MIB, Euro Stoxx 50 e S&P 100 insieme." : "");
  };
  selType.addEventListener("change", sync);
  sync();

  sheet.querySelectorAll(".sheet-close").forEach((b) =>
    b.addEventListener("click", () => sheet.remove())
  );
  sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.remove(); });

  sheet.querySelector("#form-new-auto").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = sheet.querySelector("#btn-submit-auto");
    const errEl = sheet.querySelector("#form-error");
    btn.disabled = true;
    btn.textContent = "Creazione…";
    errEl.style.display = "none";

    const fd = new FormData(e.target);
    const stratType = fd.get("strategy_type");
    const params = {};
    const FIELDS = {
      P1: { rebalance_band: parseFloat }, P2: { sma_months: parseInt },
      P3: { etf_share: parseFloat, refuge: String }, P4: { n_hold: parseInt, keep_rank: parseInt },
      P5: { max_positions: parseInt, max_days: parseInt },
      P6: { p6_n_hold: parseInt, rebalance_month: parseInt },
    };
    for (const [k, parse] of Object.entries(FIELDS[stratType] || {})) {
      const v = parse(fd.get(k));
      if (v !== "" && !(typeof v === "number" && isNaN(v))) params[k.replace(/^p6_/, "")] = v;
    }
    if (stratType === "P7") {
      const chosen = fd.getAll("sleeve");
      if (chosen.length < 2) {
        errEl.textContent = "Scegli almeno due strategie da combinare";
        errEl.style.display = "block";
        btn.disabled = false;
        btn.textContent = "Crea portafoglio";
        return;
      }
      params.sleeves = chosen.map((type) => ({ type, share: 1 }));
    }

    const body = {
      name: fd.get("name").trim(),
      strategy_type: stratType,
      universe_list: MULTI_LIST.includes(stratType) && stratType !== "P7" ? null : fd.get("universe_list"),
      initial_capital: parseFloat(fd.get("initial_capital")),
      params,
    };

    try {
      await api.post("/api/auto", body);
      sheet.remove();
      await onSuccess();
    } catch (err) {
      errEl.textContent = err.message || "Errore nella creazione";
      errEl.style.display = "block";
      btn.disabled = false;
      btn.textContent = "Crea portafoglio";
    }
  });
}

// ── Descrizioni in italiano ───────────────────────────────────────────────────

const UNIVERSE_LABELS = { ftse_mib: "FTSE MIB", eurostoxx50: "Euro Stoxx 50", sp100: "S&P 100" };

export function universeLabel(name) {
  return UNIVERSE_LABELS[name] || name || "";
}

// Liste su cui lavora un portafoglio (P3–P5 usano tutte e tre)
export function listsLabel(cfg) {
  const lists = cfg.universe_lists?.length ? cfg.universe_lists : [cfg.params?.universe_list].filter(Boolean);
  return lists.map(universeLabel).join(", ");
}

export const STRATEGY_TITLES = {
  P1: "P1 – Compra e tieni con ribilanciamento",
  P2: "P2 – Segue la tendenza (Faber)",
  P3: "P3 – Dual momentum regionale",
  P4: "P4 – Momentum con filtro di tendenza",
  P5: "P5 – Ritorno alla media (RSI a 2 giorni)",
  P6: "P6 – Valore + qualità (Magic Formula)",
  P7: "P7 – Portafoglio combinato",
};
const MULTI_LIST = ["P3", "P4", "P5", "P6", "P7"];
const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
  "ottobre", "novembre", "dicembre"];

export function strategyTitle(type) {
  return STRATEGY_TITLES[type] || type;
}

const pc = (v, d = 0) => `${(Number(v) * 100).toFixed(d).replace(".", ",")}%`;

export function strategyDescription(cfg) {
  const p = cfg.params || {};
  switch (cfg.strategy_type) {
    case "P1":
      return `Divide il capitale in parti uguali su tutti i titoli dell'elenco. Ogni giorno di borsa controlla i pesi: se un titolo si allontana più del ${pc(p.rebalance_band ?? 0.25)} dalla sua quota, compra o vende per riportarlo in linea.`;
    case "P2":
      return `Una volta al mese, a fine mese, confronta il prezzo di ogni titolo con la sua media degli ultimi ${p.sma_months ?? 10} mesi: se è sopra lo tiene o lo compra (parti uguali), se è sotto lo vende e resta in liquidità.`;
    case "P3":
      return `A fine mese confronta il rendimento in euro degli ultimi 12 mesi di Italia, Europa e Stati Uniti e investe nella regione migliore: ${pc(p.etf_share ?? 0.5)} nel suo ETF e il resto nei ${p.n_stocks ?? 10} titoli della regione saliti di più (escluso l'ultimo mese). Se nessuna regione guadagna più del ${pc(p.abs_threshold ?? 0)}, passa ${p.refuge === "cash" ? "in liquidità" : "all'ETF di titoli di Stato in euro"}.`;
    case "P4":
      return `A fine mese mette in classifica i titoli di FTSE MIB, Euro Stoxx 50 e S&P 100 per quanto sono saliti in 12 mesi (escluso l'ultimo) e tiene i primi ${p.n_hold ?? 10}. Chi è già in portafoglio resta finché è tra i primi ${p.keep_rank ?? 20}. Compra solo se l'indice della borsa del titolo è sopra la sua media a ${p.trend_days ?? 200} giorni.`;
    case "P5":
      return `Ogni giorno cerca titoli in tendenza positiva (sopra la media a ${p.sma_long ?? 200} giorni) che hanno appena avuto un forte calo (RSI a 2 giorni sotto ${p.rsi_entry ?? 10}) e li compra aspettando il rimbalzo. Vende appena il prezzo supera la media a ${p.sma_exit ?? 5} giorni, se la tendenza si rompe o dopo ${p.max_days ?? 10} giorni. Al massimo ${p.max_positions ?? 5} titoli insieme.`;
    case "P6":
      return `Una volta l'anno, ad ${MONTHS[(p.rebalance_month ?? 4) - 1]}, mette in classifica i titoli delle tre liste (escluse banche, assicurazioni e utility) per quanto rendono gli utili rispetto al prezzo dell'azienda e per quanto è redditizio il capitale investito, e compra i ${p.n_hold ?? 15} migliori in parti uguali. Usa i bilanci più recenti: per questo non ha backtest.`;
    case "P7": {
      const sl = (p.sleeves || []).map((s) => `${s.type} ${pc(s.share)}`).join(", ") || "P2, P4 e P5 in parti uguali";
      return `Mette insieme più strategie, ognuna con la sua quota del capitale (${sl}). Gli ordini sullo stesso titolo si compensano, nessuna azione supera il ${pc(p.max_weight ?? 0.1)} del totale e a ${MONTHS[(p.rebalance_month ?? 1) - 1]} le quote tornano alle percentuali stabilite.`;
    }
    default:
      return "";
  }
}

const PARAM_LABELS = {
  rebalance_band: ["Tolleranza", (v) => pc(v)],
  sma_months: ["Media su", (v) => `${v} mesi`],
  min_history_days: ["Storico minimo", (v) => `${v} giorni`],
  etf_share: ["Quota in ETF", (v) => pc(v)],
  n_stocks: ["Titoli della regione", (v) => v],
  abs_threshold: ["Soglia di rendimento", (v) => pc(v, 1)],
  refuge: ["Rifugio", (v) => (v === "cash" ? "Liquidità" : "ETF titoli di Stato")],
  etf_ita: ["ETF Italia", (v) => v],
  etf_eur: ["ETF Europa", (v) => v],
  etf_usa: ["ETF Stati Uniti", (v) => v],
  etf_refuge: ["ETF rifugio", (v) => v],
  n_hold: ["Titoli in portafoglio", (v) => v],
  keep_rank: ["Si tengono fino al posto", (v) => v],
  trend_days: ["Media dell'indice", (v) => `${v} giorni`],
  max_positions: ["Posizioni al massimo", (v) => v],
  rsi_entry: ["Compra con RSI(2) sotto", (v) => v],
  max_days: ["Vende al più tardi dopo", (v) => `${v} giorni`],
  sma_long: ["Media di tendenza", (v) => `${v} giorni`],
  sma_exit: ["Media di uscita", (v) => `${v} giorni`],
  rebalance_month: ["Mese della revisione", (v) => MONTHS[v - 1] || v],
  exclude: ["Settori esclusi", (v) => v.map((x) => ({ banks: "banche", insurance: "assicurazioni", utilities: "utility" }[x] || x)).join(", ")],
  max_weight: ["Peso massimo per azione", (v) => pc(v)],
  sleeves: ["Strategie", (v) => v.map((s) => `${s.type} ${pc(s.share)}${s.params?.universe_list ? ` (${universeLabel(s.params.universe_list)})` : ""}`).join(", ")],
};

// Parametri tecnici → righe leggibili [etichetta, valore]
export function readableParams(cfg) {
  const p = cfg.params || {};
  const rows = [["Elenco titoli", listsLabel(cfg)]];
  for (const [k, v] of Object.entries(p)) {
    if (k === "universe_list" || k === "universe_lists" || k === "risk_free") continue;
    const known = PARAM_LABELS[k];
    rows.push(known ? [known[0], String(known[1](v))] : [k, String(v)]);
  }
  return rows;
}

// ── Card portafoglio ──────────────────────────────────────────────────────────

export function dataLine(cfg) {
  const prep = cfg.preparation;
  if (prep && prep.running) {
    return `<p class="small muted" style="margin-top:.5rem">Preparazione dati: ${prep.done}/${prep.total} titoli scaricati…</p>`;
  }
  if (cfg.data_ready_pct < 75) {
    return `<p class="small muted" style="margin-top:.5rem">Dati pronti per il ${cfg.data_ready_pct}% dei titoli (servono almeno il 75%). Premi "Prova ora" per avviare il download.</p>`;
  }
  const monthly = "l'ultimo giorno di borsa del mese";
  const when = { P2: monthly, P3: monthly, P4: monthly,
    P6: `una volta l'anno, ad ${MONTHS[(cfg.params?.rebalance_month ?? 4) - 1]},` }[cfg.strategy_type] || "nei giorni di borsa";
  return `<p class="small muted" style="margin-top:.5rem">Dati pronti (${cfg.data_ready_pct}% dei titoli). Opera ${when} alle ${cfg.session === "US" ? "21:30" : "17:00"}.</p>`;
}

function configCard(cfg) {
  const statusLabel = cfg.is_paused
    ? '<span class="badge badge-muted">In pausa</span>'
    : cfg.is_drawdown_braking
    ? '<span class="badge badge-warn">Freno drawdown</span>'
    : '<span class="badge badge-ok">Attivo</span>';

  const cashLine = cfg.cash_balance != null
    ? `<div class="kv"><span class="k">Liquidità</span><span class="v">${money(cfg.cash_balance)}</span></div>`
    : "";
  const statusLine = `
    <div class="kv"><span class="k">Titoli in portafoglio</span><span class="v">${cfg.positions_count}</span></div>
    ${cfg.pending_orders ? `<div class="kv"><span class="k">Ordini in attesa</span><span class="v">${cfg.pending_orders}</span></div>` : ""}`;

  return `
    <section class="card clickable" data-auto-id="${cfg.id}">
      <div class="card-row">
        <div>
          <h3>${esc(cfg.name)}</h3>
          <div class="small muted">${esc(strategyTitle(cfg.strategy_type))} · ${esc(listsLabel(cfg))}</div>
        </div>
        ${statusLabel}
      </div>
      <p class="small" style="margin-top:.4rem">${esc(strategyDescription(cfg))}</p>
      <div class="grid2" style="margin-top:.5rem">
        ${cashLine}
        ${statusLine}
      </div>
      ${dataLine(cfg)}
      <div class="btn-row" style="margin-top:.75rem">
        <button class="btn small" data-dry-id="${cfg.id}">Prova ora</button>
        <button class="btn small btn-muted" data-pause-id="${cfg.id}">${cfg.is_paused ? "Riprendi" : "Pausa"}</button>
      </div>
    </section>`;
}
