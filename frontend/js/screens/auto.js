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
  };

  await load();
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
            <option value="P1">P1 – Buy &amp; Hold con ribilanciamento</option>
            <option value="P2">P2 – Faber Trend (10 mesi)</option>
          </select>
        </div>
        <div class="form-group">
          <label>Lista universo</label>
          <select name="universe_list" required>
            ${universiOptions || '<option value="">Nessun universo disponibile</option>'}
          </select>
        </div>
        <div class="form-group">
          <label>Capitale iniziale (€)</label>
          <input type="number" name="initial_capital" required min="1000" step="100" value="100000">
        </div>
        <div id="params-p1">
          <div class="form-group">
            <label>Banda ribilanciamento (es. 0.25 = ±25%)</label>
            <input type="number" name="rebalance_band" min="0.05" max="0.5" step="0.05" value="0.25">
          </div>
        </div>
        <div id="params-p2" style="display:none">
          <div class="form-group">
            <label>Mesi SMA (default 10)</label>
            <input type="number" name="sma_months" min="3" max="24" step="1" value="10">
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
  const paramsP1 = sheet.querySelector("#params-p1");
  const paramsP2 = sheet.querySelector("#params-p2");
  selType.addEventListener("change", () => {
    paramsP1.style.display = selType.value === "P1" ? "" : "none";
    paramsP2.style.display = selType.value === "P2" ? "" : "none";
  });

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
    if (stratType === "P1") {
      const v = parseFloat(fd.get("rebalance_band"));
      if (!isNaN(v)) params.rebalance_band = v;
    } else if (stratType === "P2") {
      const v = parseInt(fd.get("sma_months"), 10);
      if (!isNaN(v)) params.sma_months = v;
    }

    const body = {
      name: fd.get("name").trim(),
      strategy_type: stratType,
      universe_list: fd.get("universe_list"),
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

// ── Card portafoglio ──────────────────────────────────────────────────────────

function configCard(cfg) {
  const statusLabel = cfg.is_paused
    ? '<span class="badge badge-muted">In pausa</span>'
    : cfg.is_drawdown_braking
    ? '<span class="badge badge-warn">Freno drawdown</span>'
    : '<span class="badge badge-ok">Attivo</span>';

  const cashLine = cfg.cash_balance != null
    ? `<div class="kv"><span class="k">Liquidità</span><span class="v">${money(cfg.cash_balance)}</span></div>`
    : "";

  return `
    <section class="card clickable" data-auto-id="${cfg.id}">
      <div class="card-row">
        <div>
          <h3>${esc(cfg.name)}</h3>
          <div class="small muted">${esc(cfg.strategy_type)} · ${esc(cfg.params?.universe_list || "")}</div>
        </div>
        ${statusLabel}
      </div>
      <div class="grid2" style="margin-top:.5rem">
        ${cashLine}
      </div>
      <div class="btn-row" style="margin-top:.75rem">
        <button class="btn small" data-dry-id="${cfg.id}">Prova ora</button>
        <button class="btn small btn-muted" data-pause-id="${cfg.id}">${cfg.is_paused ? "Riprendi" : "Pausa"}</button>
      </div>
    </section>`;
}
