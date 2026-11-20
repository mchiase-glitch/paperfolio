import { api } from "../api.js";
import { refreshAccount, toast } from "../app.js";
import { esc, fromPercent, money, toPercent, TYPE_LABELS } from "../format.js";

let commType = "stock";

export async function renderSettings(el) {
  const s = await api.get("/api/settings");
  const pctInput = (id, value) => `<input type="text" inputmode="decimal" id="${id}" value="${toPercent(value)}">`;
  el.innerHTML = `
    <section class="card">
      <h2>Parametri generali</h2>
      <label class="field"><span>Spread di cambio (%), sempre a sfavore</span>${pctInput("fx_spread", s.fx_spread)}</label>
      <label class="field"><span>Margine di prenotazione ordini in attesa (%)</span>${pctInput("reservation_margin", s.reservation_margin)}</label>
      <label class="field"><span>Tobin tax su acquisti di azioni italiane (%)</span>${pctInput("tobin_rate", s.tobin_rate)}</label>
      <label class="field"><span>Imposta di bollo annua (%)</span>${pctInput("stamp_duty_rate", s.stamp_duty_rate)}</label>
    </section>

    <section class="card">
      <h2>Commissioni</h2>
      <div class="chips">${Object.keys(TYPE_LABELS).map((t) => `<button class="chip ${t === commType ? "active" : ""}" data-ct="${t}">${TYPE_LABELS[t]}</button>`).join("")}</div>
      <div class="scroll-x"><table class="compact">
        <tr><th>Mercato</th><th>Fisso €</th><th>%</th><th>Minimo €</th></tr>
        ${s.commissions.map((c) => `<tr data-comm="${c.id}" data-type="${c.instrument_type}" ${c.instrument_type === commType ? "" : "hidden"}>
          <td>${c.market}</td>
          <td><input type="text" inputmode="decimal" data-f="fixed_eur" value="${c.fixed_eur}"></td>
          <td><input type="text" inputmode="decimal" data-f="pct" value="${toPercent(c.pct)}"></td>
          <td><input type="text" inputmode="decimal" data-f="minimum_eur" value="${c.minimum_eur}"></td></tr>`).join("")}
      </table></div>
      <div class="small muted" style="margin-top:6px">Commissione = max(fisso + % × controvalore in EUR, minimo)</div>
    </section>

    <section class="card">
      <h2>Aliquote per categoria fiscale</h2>
      <div class="scroll-x"><table class="compact">
        <tr><th>Categoria</th><th>Aliquota %</th><th>Base imponibile %</th></tr>
        ${s.tax_rules.map((r) => `<tr data-tax="${r.fiscal_category}">
          <td>${esc(r.label)}<div class="small muted">plus: ${r.gains_kind === "diversi" ? "redditi diversi" : "redditi di capitale"}</div></td>
          <td><input type="text" inputmode="decimal" data-f="rate" value="${toPercent(r.rate)}"></td>
          <td><input type="text" inputmode="decimal" data-f="base_factor" value="${toPercent(r.base_factor)}"></td></tr>`).join("")}
      </table></div>
    </section>

    <section class="card">
      <h2>Ritenute alla fonte sui dividendi esteri</h2>
      <div class="scroll-x"><table class="compact" id="wh">
        <tr><th>Paese</th><th>Ritenuta %</th></tr>
        ${s.withholding.map((w) => `<tr><td><input type="text" maxlength="2" data-f="country" value="${w.country}"></td>
          <td><input type="text" inputmode="decimal" data-f="rate" value="${toPercent(w.rate)}"></td></tr>`).join("")}
      </table></div>
      <button class="btn small" id="add-wh" style="margin-top:8px">+ Aggiungi paese</button>
      <div class="small muted" style="margin-top:6px">Usate dalla fase 2 (dividendi). Dopo la ritenuta estera si applica il 26% italiano sul netto.</div>
    </section>

    <button class="btn primary block" id="save">Salva impostazioni</button>
    <div class="error small" id="err"></div>

    <section class="card" style="margin-top:20px">
      <h2>Portafogli</h2>
      <div class="small muted" style="margin-bottom:8px">Puoi tenere più portafogli separati (es. "Prudente" e "Dinamico") e passare dall'uno all'altro con il pulsante in alto a destra. Commissioni, aliquote e parametri qui sopra valgono per tutti.</div>
      <div id="accounts"></div>
      <label class="field"><span>Nome del portafoglio attivo</span><input type="text" id="acc-name" maxlength="60"></label>
      <button class="btn block" id="rename">Rinomina</button>
      <div class="divider"></div>
      <div class="grid2">
        <label class="field"><span>Nuovo portafoglio</span><input type="text" id="new-name" maxlength="60" placeholder="Nome"></label>
        <label class="field"><span>Capitale (€)</span><input type="text" inputmode="decimal" id="new-capital" value="10000"></label>
      </div>
      <button class="btn primary block" id="create">Crea portafoglio</button>
      <button class="btn block" id="close-acc" style="margin-top:8px">Chiudi il portafoglio attivo</button>
    </section>

    <section class="card">
      <h2>Reset del portafoglio attivo</h2>
      <div class="small muted" style="margin-bottom:10px">Capitale attuale: ${money(s.initial_capital)}. Il reset addebita il bollo maturato, annulla gli ordini in attesa e riparte da zero con il capitale indicato. Lo storico resta nel database.</div>
      <label class="field"><span>Nuovo capitale iniziale (€)</span><input type="text" inputmode="decimal" id="capital" value="${s.initial_capital}"></label>
      <button class="btn sell block" id="reset">Azzera portafoglio</button>
    </section>`;

  el.querySelectorAll("[data-ct]").forEach((b) => b.addEventListener("click", () => {
    commType = b.dataset.ct;
    el.querySelectorAll("[data-ct]").forEach((x) => x.classList.toggle("active", x === b));
    el.querySelectorAll("[data-comm]").forEach((tr) => (tr.hidden = tr.dataset.type !== commType));
  }));
  el.querySelector("#add-wh").addEventListener("click", () => el.querySelector("#wh").insertAdjacentHTML("beforeend",
    `<tr><td><input type="text" maxlength="2" data-f="country"></td><td><input type="text" inputmode="decimal" data-f="rate"></td></tr>`));

  const dec = (v) => String(v).trim().replace(",", ".");
  el.querySelector("#save").addEventListener("click", async () => {
    const err = el.querySelector("#err");
    err.textContent = "";
    const f = (tr, name) => tr.querySelector(`[data-f="${name}"]`).value;
    const body = {
      fx_spread: fromPercent(el.querySelector("#fx_spread").value),
      reservation_margin: fromPercent(el.querySelector("#reservation_margin").value),
      tobin_rate: fromPercent(el.querySelector("#tobin_rate").value),
      stamp_duty_rate: fromPercent(el.querySelector("#stamp_duty_rate").value),
      commissions: [...el.querySelectorAll("[data-comm]")].map((tr) => ({
        id: Number(tr.dataset.comm), fixed_eur: dec(f(tr, "fixed_eur")), pct: fromPercent(f(tr, "pct")), minimum_eur: dec(f(tr, "minimum_eur")),
      })),
      tax_rules: [...el.querySelectorAll("[data-tax]")].map((tr) => ({
        fiscal_category: tr.dataset.tax, rate: fromPercent(f(tr, "rate")), base_factor: fromPercent(f(tr, "base_factor")),
      })),
      withholding: [...el.querySelectorAll("#wh tr")].slice(1)
        .map((tr) => ({ country: f(tr, "country").trim().toUpperCase(), rate: fromPercent(f(tr, "rate")) }))
        .filter((w) => w.country),
    };
    try {
      await api.put("/api/settings", body);
      toast("Impostazioni salvate");
      renderSettings(el);
    } catch (e) { err.textContent = e.message; }
  });

  // --- Portafogli ---
  const { accounts } = await api.get("/api/accounts");
  const cur = accounts.find((a) => a.current);
  el.querySelector("#accounts").innerHTML = accounts.map((a) => `<div class="row"><span class="k">${esc(a.name)}${a.current ? ' <span class="tag">attivo</span>' : ""}</span><span class="v">${money(a.total_value)}</span></div>`).join("");
  el.querySelector("#acc-name").value = cur?.name ?? "";
  const done = async (msg) => { toast(msg); await refreshAccount(); renderSettings(el); };
  el.querySelector("#rename").addEventListener("click", async () => {
    try { await api.put(`/api/accounts/${cur.id}`, { name: el.querySelector("#acc-name").value.trim() }); done("Portafoglio rinominato"); }
    catch (e) { toast(e.message); }
  });
  el.querySelector("#create").addEventListener("click", async () => {
    const name = el.querySelector("#new-name").value.trim();
    const capital = dec(el.querySelector("#new-capital").value).replace(/\.(?=\d{3}(\D|$))/g, "");
    if (!name) { toast("Dai un nome al nuovo portafoglio"); return; }
    try { await api.post("/api/accounts", { name, capital }); done(`Creato "${name}": ora è il portafoglio attivo`); }
    catch (e) { toast(e.message); }
  });
  el.querySelector("#close-acc").addEventListener("click", async () => {
    if (accounts.length < 2) { toast("È l'unico portafoglio: per ripartire usa il reset qui sotto"); return; }
    if (!confirm(`Chiudere "${cur.name}"? Il bollo maturato viene addebitato e gli ordini in attesa annullati. Non si potrà riaprire.`)) return;
    try { await api.post(`/api/accounts/${cur.id}/close`, { confirm: true }); done("Portafoglio chiuso"); }
    catch (e) { toast(e.message); }
  });

  el.querySelector("#reset").addEventListener("click", async () => {
    const capital = dec(el.querySelector("#capital").value);
    if (!confirm(`Azzerare il portafoglio e ripartire con ${money(capital)}? L'operazione non si può annullare.`)) return;
    try {
      await api.post("/api/settings/reset", { capital, confirm: true });
      toast("Portafoglio azzerato");
      location.hash = "#/";
    } catch (e) { toast(e.message); }
  });
}
