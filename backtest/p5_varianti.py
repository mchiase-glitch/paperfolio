"""
Backtest delle varianti di P5 (vedi CONTEXT_P5_varianti.md) e report in reports/p5_varianti/.

uso (dalla cartella del progetto):
    backend/.venv/Scripts/python.exe backtest/p5_varianti.py <database.db> [--varianti V0,V1] [--costi attuale,basso]
                                                             [--rsi 5,10,15] [--out cartella]

- Usa solo i dati già in cache (non scarica nulla), così rilanciando si ottengono gli stessi numeri.
- Periodo 1/1/2010–25/11/2026, 100.000 €, prova fino al 31/12/2018 e verifica dal 1/1/2019.
- `--rsi` sostituisce la soglia di entrata (solo per il test di robustezza della fase 3).

Definizioni usate nel report:
- "lordo" di un'operazione: risultato ai prezzi di mercato (senza commissioni, Tobin, spread di cambio
  né slippage), in % del valore di acquisto;
- "costo per giro": commissioni + Tobin + spread di cambio + slippage di acquisto e vendita, nella stessa base;
- le posizioni ancora aperte alla fine non entrano nelle statistiche per operazione.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

START, END, SPLIT = date(2010, 1, 1), date(2026, 11, 25), date(2019, 1, 1)
CAPITAL = Decimal("100000")
SLIPPAGE = 0.0005

VARIANTS = {
    "V0": ({}, {}, "nessuna modifica (riferimento)"),
    "V1": ({}, {"execution": "close", "slippage": SLIPPAGE},
           "esecuzione alla chiusura del giorno del segnale, slippage 0,05% per lato"),
    "V2": ({"exit_below_sma_long": False}, {}, "senza uscita sotto la media a 200"),
    "V3": ({"drawdown_brake": False}, {}, "senza freno sul drawdown"),
    "V4": ({"rsi_entry": 5}, {}, "entrata con RSI(2) < 5"),
    "V5": ({"exit_below_sma_long": False, "drawdown_brake": False}, {"execution": "close", "slippage": SLIPPAGE},
           "V1 + V2 + V3"),
}
COSTS = {"attuale": "current", "basso": "low"}
COST_LABEL = {"attuale": "C-attuale", "basso": "C-basso"}
MARKET_LABEL = {"USA": "USA", "ITA": "Italia", "EUR": "Europa"}


def exit_reason(reason: str) -> str:
    if "rimbalzo avvenuto" in reason:
        return "sopra la media a 5 (rimbalzo)"
    if "tendenza persa" in reason:
        return "sotto la media a 200"
    if "stop temporale" in reason:
        return "stop temporale 10 giorni"
    return "altro"


def pct(x, digits=1, sign=True):
    return "—" if x is None else f"{x * 100:{'+' if sign else ''}.{digits}f}%".replace(".", ",")


def dec(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}".replace(".", ",")


def num(x, digits=0):
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def round_trips(trades, markets, fx_spread: float, slippage: float):
    """Abbina ogni vendita all'acquisto che ha aperto la posizione (P5 apre con un solo acquisto)."""
    open_buy, out = {}, []
    for t in trades:
        if t.side not in ("buy", "sell"):
            continue
        gross, comm = float(t.gross_eur), float(t.costs_eur)
        foreign = t.currency != "EUR"
        spread = gross * fx_spread if foreign else 0.0
        if t.side == "buy":
            slip = gross * slippage / (1 + slippage)
            open_buy[t.symbol] = (t, gross, comm, spread, slip)
            continue
        slip = gross * slippage / (1 - slippage) if slippage else 0.0
        b = open_buy.pop(t.symbol, None)
        if b is None:
            continue
        bt, b_gross, b_comm, b_spread, b_slip = b
        base = b_gross - b_spread - b_slip          # valore di acquisto ai prezzi di mercato
        market_result = (gross + spread + slip) - base
        cost = b_comm + comm + b_spread + spread + b_slip + slip
        out.append({
            "simbolo": t.symbol, "mercato": MARKET_LABEL.get(markets.get(t.symbol), markets.get(t.symbol)),
            "acquisto": bt.day.isoformat(), "vendita": t.day.isoformat(), "motivo_uscita": exit_reason(t.reason),
            "valore_acquisto_eur": round(base, 2), "lordo_eur": round(market_result, 2),
            "lordo_pct": market_result / base, "costi_eur": round(cost, 2), "costo_pct": cost / base,
            "netto_prima_imposte_eur": round(market_result - cost, 2),
        })
    return out, len(open_buy)


def run_one(db, code, cost_key, rsi=None):
    from app.models import BacktestRun, BacktestTrade, Instrument
    from app.services import backtest
    from sqlalchemy import select

    params, options, _ = VARIANTS[code]
    params = dict(params)
    if rsi is not None:
        params["rsi_entry"] = rsi
    params["backtest_options"] = {**options, "costs": COSTS[cost_key]}
    run = BacktestRun(strategy_type="P5", strategy_version="variante", params_json=json.dumps(params),
                      start_date=START, end_date=END, split_date=SPLIT, initial_capital=CAPITAL,
                      status="running", progress=0)
    db.add(run)
    db.commit()
    backtest.execute(db, run, fetch=False)
    results = json.loads(run.results_json)
    trades = db.scalars(select(BacktestTrade).where(BacktestTrade.run_id == run.id)
                        .order_by(BacktestTrade.day, BacktestTrade.id)).all()
    markets = dict(db.execute(select(Instrument.symbol, Instrument.market)).all())
    costs = backtest.apply_cost_scenario(backtest.load_costs(db), COSTS[cost_key])
    trips, still_open = round_trips(trades, markets, float(costs.fx_spread), float(options.get("slippage", 0)))
    return params, results, trips, still_open


def summarize(code, cost_key, rsi, params, r, trips, still_open):
    p = r["periods"]
    s = {k: p[k]["strategy"] for k in ("full", "in_sample", "out_of_sample")}
    c = {k: float(v) for k, v in r["costs"].items()}
    lordo = [t["lordo_pct"] for t in trips]
    cost = [t["costo_pct"] for t in trips]
    return {
        "variante": code + (f" RSI<{rsi}" if rsi is not None else ""), "costi": COST_LABEL[cost_key],
        "netto_totale": s["full"]["cagr"], "netto_prova": s["in_sample"]["cagr"],
        "netto_verifica": s["out_of_sample"]["cagr"], "volatilita": s["full"]["volatility"],
        "perdita_massima": s["full"]["max_drawdown"], "sharpe": s["full"]["sharpe"],
        "valore_finale": float(r["liquidation_value"]), "acquisti": r["buys"], "rotazione": r["turnover"],
        "commissioni": c["commissions"], "tobin": c["tobin"],
        "imposte": c["capital_gain_tax"] + c["dividend_tax"] + c["withholding"],
        "imposta_plusvalenze": c["capital_gain_tax"], "imposte_dividendi": c["dividend_tax"] + c["withholding"],
        "bollo": c["stamp"], "operazioni_chiuse": len(trips), "posizioni_aperte_fine": still_open,
        "lordo_medio": statistics.mean(lordo) if lordo else None,
        "lordo_mediano": statistics.median(lordo) if lordo else None,
        "costo_medio_giro": statistics.mean(cost) if cost else None,
        "giorni_freno": r["days_braking"], "ordini_scartati": r["dropped_orders"],
    }


def group_table(trips, key):
    g = defaultdict(list)
    for t in trips:
        g[t[key]].append(t)
    return g


def write_report(out: Path, name: str, code: str, cost_key: str, summ: dict, params: dict, trips: list):
    with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trips[0]) if trips else ["simbolo"], delimiter=";")
        w.writeheader()
        for t in trips:
            w.writerow({k: (f"{v:.6f}" if isinstance(v, float) and k.endswith("_pct") else v) for k, v in t.items()})

    lines = [
        f"# P5 {summ['variante']} — {summ['costi']}",
        "",
        f"*Modifica rispetto a V0:* {VARIANTS[code][2]}. Parametri: `{json.dumps(params)}`.",
        f"Periodo {START:%d/%m/%Y}–{END:%d/%m/%Y}, {num(float(CAPITAL))} € iniziali; prova fino al 31/12/2018, "
        "verifica dal 1/1/2019. Solo dati già in cache.",
        "",
    ]
    if VARIANTS[code][1].get("execution") == "close":
        lines += ["**Esecuzione:** alla chiusura del giorno del segnale (approssima un ordine al prezzo di chiusura "
                  "inviato poco prima della fine della seduta), con **slippage dello 0,05% per lato** a sfavore.", ""]
    if cost_key == "basso":
        lines += ["**Costi C-basso:** 0,025% per lato senza parte fissa, minimo 1 €; conto multivaluta senza spread "
                  "di cambio su operazioni e dividendi (la conversione iniziale unica non è addebitata); "
                  "Tobin tax e imposte invariate.", ""]
    lines += [
        "## Risultati",
        "",
        "| | Totale | Prova 2010–2018 | Verifica 2019–2026 |",
        "|---|---|---|---|",
        f"| Rendimento annuo netto | {pct(summ['netto_totale'])} | {pct(summ['netto_prova'])} | "
        f"{pct(summ['netto_verifica'])} |",
        "",
        f"- Valore finale (netto se si vendesse tutto): {num(summ['valore_finale'])} €",
        f"- Volatilità annua {pct(summ['volatilita'], sign=False)}, perdita massima {pct(summ['perdita_massima'])}, "
        f"Sharpe {dec(summ['sharpe'], 2)}",
        f"- Acquisti {num(summ['acquisti'])}, rotazione annua {dec(summ['rotazione'], 1)} volte il capitale",
        f"- Giorni con il freno sul drawdown acceso: {num(summ['giorni_freno'])}",
        f"- Ordini non eseguiti: {summ['ordini_scartati']}",
        "",
        "## Costi e imposte",
        "",
        f"- Commissioni {num(summ['commissioni'])} €, Tobin tax {num(summ['tobin'])} €",
        f"- Imposte {num(summ['imposte'])} € (plusvalenze {num(summ['imposta_plusvalenze'])} €, dividendi con "
        f"ritenute {num(summ['imposte_dividendi'])} €), bollo {num(summ['bollo'])} €",
        "",
        "## Operazioni",
        "",
        f"- Operazioni chiuse {num(summ['operazioni_chiuse'])} (posizioni ancora aperte alla fine: "
        f"{summ['posizioni_aperte_fine']}, escluse)",
        f"- Rendimento lordo medio per operazione {pct(summ['lordo_medio'], 2)}, mediano "
        f"{pct(summ['lordo_mediano'], 2)}",
        f"- Costo medio per giro {pct(summ['costo_medio_giro'], 2)} (commissioni, Tobin, spread di cambio, slippage)",
        "",
        "### Per motivo di uscita",
        "",
        "| Motivo | Vendite | Lordo medio | Lordo medio € | In utile (lordo) |",
        "|---|---|---|---|---|",
    ]
    for reason, ts in sorted(group_table(trips, "motivo_uscita").items()):
        lines.append(f"| {reason} | {num(len(ts))} | {pct(statistics.mean(t['lordo_pct'] for t in ts), 2)} | "
                     f"{num(statistics.mean(t['lordo_eur'] for t in ts))} € | "
                     f"{sum(t['lordo_eur'] > 0 for t in ts) / len(ts) * 100:.0f}% |")
    lines += ["", "### Per mercato", "",
              "| Mercato | Operazioni | Lordo medio | Lordo totale | Costi totali | Costo medio per giro |",
              "|---|---|---|---|---|---|"]
    for mkt, ts in sorted(group_table(trips, "mercato").items(), key=lambda kv: str(kv[0])):
        lines.append(f"| {mkt} | {num(len(ts))} | {pct(statistics.mean(t['lordo_pct'] for t in ts), 2)} | "
                     f"{num(sum(t['lordo_eur'] for t in ts))} € | {num(sum(t['costi_eur'] for t in ts))} € | "
                     f"{pct(statistics.mean(t['costo_pct'] for t in ts), 2)} |")
    lines += ["", f"Dettaglio di ogni operazione: `{name}.csv`.", ""]
    (out / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")


def write_comparison(out: Path, rows: list[dict], tag: str):
    fields = list(rows[0])
    with open(out / f"confronto{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    lines = [
        "# P5 — confronto delle varianti",
        "",
        f"Periodo {START:%d/%m/%Y}–{END:%d/%m/%Y}, 100.000 €; prova 2010–2018, verifica 2019–2026. "
        "Lordo = ai prezzi di mercato; costo per giro = commissioni + Tobin + spread di cambio + slippage. "
        "V1 e V5 hanno lo slippage dello 0,05% per lato.",
        "",
        "| Variante | Costi | Netto totale | Netto prova | Netto verifica | Perdita massima | Sharpe | Volatilità | "
        "Acquisti | Rotazione | Lordo medio | Lordo mediano | Costo per giro | Commissioni | Tobin | Imposte | Bollo | "
        "Giorni freno | Valore finale |",
        "|" + "---|" * 19,
    ]
    for r in rows:
        lines.append(
            f"| {r['variante']} | {r['costi']} | {pct(r['netto_totale'])} | {pct(r['netto_prova'])} | "
            f"{pct(r['netto_verifica'])} | {pct(r['perdita_massima'])} | {dec(r['sharpe'], 2)} | "
            f"{pct(r['volatilita'], sign=False)} | {num(r['acquisti'])} | {dec(r['rotazione'], 1)}"
            f" | {pct(r['lordo_medio'], 2)} | {pct(r['lordo_mediano'], 2)} | {pct(r['costo_medio_giro'], 2)} | "
            f"{num(r['commissioni'])} € | {num(r['tobin'])} € | {num(r['imposte'])} € | {num(r['bollo'])} € | "
            f"{num(r['giorni_freno'])} | {num(r['valore_finale'])} € |")
    lines.append("")
    (out / f"confronto{tag}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--varianti", default=",".join(VARIANTS))
    ap.add_argument("--costi", default="attuale,basso")
    ap.add_argument("--rsi", default="")
    ap.add_argument("--out", default=str(ROOT / "backtest" / "reports" / "p5_varianti"))
    a = ap.parse_args()

    os.environ["ENABLE_SCHEDULER"] = "0"
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(a.db).resolve()}"
    sys.path.insert(0, str(ROOT / "backend"))
    from app.database import SessionLocal, engine
    from app.migrate import upgrade_to_head
    with engine.begin() as conn:
        upgrade_to_head(conn)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rsis = [int(x) for x in a.rsi.split(",") if x] or [None]
    rows = []
    for code in a.varianti.split(","):
        for cost_key in a.costi.split(","):
            for rsi in rsis:
                t0 = time.time()
                with SessionLocal() as db:
                    params, r, trips, still_open = run_one(db, code, cost_key, rsi)
                summ = summarize(code, cost_key, rsi, params, r, trips, still_open)
                name = f"P5_{code}_{COST_LABEL[cost_key]}" + (f"_RSI{rsi}" if rsi is not None else "")
                write_report(out, name, code, cost_key, summ, params, trips)
                rows.append(summ)
                print(f"{name}: {time.time() - t0:.0f}s netto {pct(summ['netto_totale'])} prova "
                      f"{pct(summ['netto_prova'])} verifica {pct(summ['netto_verifica'])} "
                      f"maxDD {pct(summ['perdita_massima'])}", flush=True)
    write_comparison(out, rows, "_robustezza" if rsis != [None] else "")


if __name__ == "__main__":
    main()
