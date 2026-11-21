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
      el.innerHTML = `<div class="card error">${esc(e.message)}</div>`;
      return;
    }

    if (!configs.length) {
      el.innerHTML = `
        <section class="card">
          <p class="muted" style="text-align:center;padding:2rem 1rem">
            Nessun portafoglio automatico configurato.
          </p>
        </section>`;
      return;
    }

    el.innerHTML = `
      <section class="card">
        <h2>Portafogli automatici</h2>
        <p class="small muted">Strategie a regole fisse che operano in autonomia sui mercati.</p>
      </section>
      ${configs.map(configCard).join("")}`;

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
          const r = await api.patch(`/api/auto/${id}/pause`);
          btn.textContent = r.is_paused ? "Riprendi" : "Pausa";
          btn.classList.toggle("btn-muted", r.is_paused);
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
          const r = await api.post(`/api/auto/${id}/run_now`);
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
