"""Backtest: dati di prova piccoli con risultato calcolato a mano, metriche, coerenza dei costi col vivo."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.models import BacktestTrade, PriceHistoryCache, StrategyConfig
from app.services import backtest as bt
from app.services import metrics, orders
from app.services.backtest import (
    BacktestEngine, CommRule, Costs, InstrumentInfo, Series, TaxInfo, load_costs,
)
from app.services.price_history import DayRow
from app.services.prices import PriceInfo
from app.services.strategies.base import BaseStrategy, Decision
from app.services.strategies.p1_buy_hold import P1BuyHold

from .conftest import OPEN_MIL, add_stock

MON = date(2025, 3, 3)  # lunedì


def days(n, start=MON):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def series(closes, opens=None, dividends=None, start=MON):
    ds = days(len(closes), start)
    opens = opens or closes
    dividends = dividends or [0.0] * len(closes)
    return Series([DayRow(d, o, o, c, c, 0, dv, 1.0) for d, o, c, dv in zip(ds, opens, closes, dividends)])


def costs(comm=CommRule(D("0"), D("0"), D("0")), tobin="0", spread="0", stamp="0", withholding=None):
    return Costs(
        commissions={("stock", "ITA"): comm, ("stock", "USA"): comm},
        tax_rules={"azioni": TaxInfo(D("0.26"), D("1"), "diversi", "diversi")},
        withholding=withholding or {}, tobin_rate=D(tobin), fx_spread=D(spread), stamp_rate=D(stamp),
    )


def it(symbol):
    return InstrumentInfo(symbol, "stock", "ITA", "IT", "EUR", "azioni")


class Scripted(BaseStrategy):
    """Strategia di prova: compra o vende ai giorni indicati, con il peso indicato."""

    def __init__(self, plan):
        super().__init__(None, {})
        self.plan = plan  # {date: [(symbol, action, weight)]}

    frequency = "daily"

    def should_run_today(self, today, next_day=None):
        return today in self.plan

    def generate_decisions(self, ctx, universe_prices, drawdown_braking):
        return [Decision(s, a, D(w), f"piano {a}") for s, a, w in self.plan.get(ctx.today, [])]


def engine(strategy, data, capital="1000", c=None, instruments=None, fx=None):
    ds = [d for s in data.values() for d in s.dates]
    return BacktestEngine(strategy, list(data), instruments or {s: it(s) for s in data}, data, fx or {},
                          c or costs(), min(ds), max(ds), D(capital))


# ── Esecuzione ────────────────────────────────────────────────────────────────

def test_p1_buys_equal_weights_at_next_open():
    data = {"A": series([10] * 5), "B": series([20] * 5)}
    res = engine(P1BuyHold(None, {"rebalance_band": 0.25}), data).run()
    buys = [t for t in res.trades if t.side == "buy"]
    # 1000 × 50% × 0,98 = 490 € → 49 A a 10 €, 24 B a 20 €; eseguiti il secondo giorno
    assert {(t.symbol, t.qty, t.day) for t in buys} == {("A", 49, days(2)[1]), ("B", 24, days(2)[1])}
    assert res.final_value == D("1000")
    assert res.curve[-1][1] == 1000


def test_execution_uses_next_day_open_not_signal_close():
    plan = {MON: [("A", "buy", "0.5")]}
    data = {"A": series([10, 12, 12], opens=[10, 11, 12])}
    res = engine(Scripted(plan), data).run()
    (buy,) = [t for t in res.trades if t.side == "buy"]
    assert buy.price == D("11") and buy.qty == 49  # quantità decisa alla chiusura di 10 €, prezzo di apertura 11 €


def test_buy_reduced_when_open_gaps_up():
    plan = {MON: [("A", "buy", "1")]}
    data = {"A": series([10, 20, 20], opens=[10, 20, 20])}
    res = engine(Scripted(plan), data).run()
    (buy,) = [t for t in res.trades if t.side == "buy"]
    assert buy.qty == 50  # 98 decise a 10 €, ma a 20 € con 1000 € se ne comprano 50


def test_capital_gain_tax_and_loss_offset():
    d = days(8)
    plan = {d[0]: [("A", "buy", "1")], d[2]: [("A", "sell", "0")],
            d[4]: [("A", "buy", "1")], d[6]: [("A", "sell", "0")]}
    # Compra 98 a 10, vende a 8 (minus 196), ricompra a 8, vende a 12 (plus 4 × 120 = 480)
    data = {"A": series([10, 10, 8, 8, 8, 8, 12, 12])}
    res = engine(Scripted(plan), data).run()
    sells = [t for t in res.trades if t.side == "sell"]
    assert sells[0].tax_eur == 0 and sells[0].realized_eur == D("-196.00")
    second_qty = sells[1].qty
    gain = second_qty * 4
    assert sells[1].tax_eur == ((gain - D("196")) * D("0.26")).quantize(D("0.01"))


def test_commissions_and_tobin_on_italian_buy():
    plan = {MON: [("A", "buy", "1")]}
    c = costs(comm=CommRule(D("2"), D("0.001"), D("5")), tobin="0.001")
    res = engine(Scripted(plan), {"A": series([10, 10, 10])}, capital="10000", c=c).run()
    (buy,) = [t for t in res.trades if t.side == "buy"]
    gross = buy.qty * 10
    comm = max(D("2") + gross * D("0.001"), D("5")).quantize(D("0.01"))
    assert buy.costs_eur == comm + (gross * D("0.001")).quantize(D("0.01"))
    assert res.totals.tobin == (gross * D("0.001")).quantize(D("0.01"))


def test_foreign_dividend_withholding_and_italian_tax():
    plan = {MON: [("X", "buy", "1")]}
    usd = InstrumentInfo("X", "stock", "USA", "US", "USD", "azioni")
    data = {"X": series([10, 10, 10, 10], dividends=[0, 0, 1.0, 0])}
    fx = {"USD": series([2.0] * 4)}  # 2 USD per 1 EUR
    res = engine(Scripted(plan), data, capital="1000", c=costs(withholding={"US": D("0.15")}),
                 instruments={"X": usd}, fx=fx).run()
    (div,) = [t for t in res.trades if t.side == "dividend"]
    qty = [t for t in res.trades if t.side == "buy"][0].qty  # 1000×0,98 / (10/2) = 196
    gross = (qty * 1 / D("2")).quantize(D("0.01"))
    withholding = (gross * D("0.15")).quantize(D("0.01"))
    tax = ((gross - withholding) * D("0.26")).quantize(D("0.01"))
    assert qty == 196 and div.gross_eur == gross and div.cash_delta_eur == gross - withholding - tax


def test_dividend_not_paid_on_shares_bought_on_ex_date():
    plan = {MON: [("A", "buy", "1")]}
    data = {"A": series([10, 10, 10], dividends=[0, 1.0, 0])}  # stacco il giorno dell'acquisto
    res = engine(Scripted(plan), data).run()
    assert not [t for t in res.trades if t.side == "dividend"]


def test_stamp_duty_pro_rata_over_a_year():
    start = date(2024, 1, 1)
    ds = days(400, start)
    data = {"A": series([10] * 400, start=start)}
    plan = {ds[0]: [("A", "buy", "1")]}
    res = engine(Scripted(plan), data, capital="100000", c=costs(stamp="0.002")).run()
    stamps = [t for t in res.trades if t.side == "stamp"]
    # 9.800 azioni × 10 € = 98.000 €, dal 2 gennaio al 31 dicembre 2024 (365 giorni su 366)
    assert stamps[0].tax_eur == (D("98000") * D("0.002") * 365 / 366).quantize(D("0.01"))
    assert len(stamps) == 2  # il secondo è il pro rata del 2025 alla fine del backtest


def test_liquidation_value_includes_latent_tax():
    plan = {MON: [("A", "buy", "1")]}
    res = engine(Scripted(plan), {"A": series([10, 10, 20])}).run()
    gain = D("98") * 10
    assert res.final_value == D("20") + D("98") * 20
    assert res.liquidation_value == res.final_value - (gain * D("0.26")).quantize(D("0.01"))


def test_drawdown_brake_blocks_buys_in_backtest():
    d = days(6)
    data = {"A": series([10, 10, 7, 7, 7, 7]), "B": series([10] * 6)}

    class BuyB(Scripted):
        def generate_decisions(self, ctx, ups, braking):
            self.seen = getattr(self, "seen", []) + [(ctx.today, braking)]
            return super().generate_decisions(ctx, ups, braking)

    s = BuyB({d[0]: [("A", "buy", "1")], d[3]: [("B", "buy", "0.5")]})
    res = engine(s, data).run()
    assert dict(s.seen)[d[3]] is True  # 98 × 7 + 20 = 706 su un massimo di 1000: -29%


def test_drawdown_brake_can_be_disabled_per_strategy():
    d = days(6)
    data = {"A": series([10, 10, 7, 7, 7, 7]), "B": series([10] * 6)}

    class BuyB(Scripted):
        def generate_decisions(self, ctx, ups, braking):
            self.seen = getattr(self, "seen", []) + [(ctx.today, braking)]
            return super().generate_decisions(ctx, ups, braking)

    s = BuyB({d[0]: [("A", "buy", "1")], d[3]: [("B", "buy", "0.5")]})
    s.params = {"drawdown_brake": False}
    res = engine(s, data).run()
    assert dict(s.seen)[d[3]] is False and res.days_braking == 0


def test_execution_at_signal_close_with_slippage():
    d = days(4)
    plan = {d[0]: [("A", "buy", "0.5")], d[2]: [("A", "sell", "0")]}
    data = {"A": series([10, 12, 14, 14], opens=[10, 11, 13, 14])}
    e = engine(Scripted(plan), data)
    e.options = bt.EngineOptions(execution="close", slippage=D("0.01"))
    res = e.run()
    buy, sell = [t for t in res.trades if t.side in ("buy", "sell")]
    assert (buy.day, buy.price, buy.qty) == (d[0], D("10.10"), 49)  # stesso giorno, chiusura 10 + 1%
    assert (sell.day, sell.price) == (d[2], D("13.86"))  # chiusura 14 − 1%


def test_engine_options_from_params():
    o = bt.EngineOptions.from_params({"backtest_options": {"execution": "close", "slippage": 0.0005, "costs": "low"}})
    assert (o.execution, o.slippage, o.costs) == ("close", D("0.0005"), "low")
    assert bt.EngineOptions.from_params({}) == bt.EngineOptions()
    with pytest.raises(ValueError):
        bt.EngineOptions.from_params({"backtest_options": {"execution": "domani"}})


def test_low_cost_scenario():
    c = bt.apply_cost_scenario(costs(comm=CommRule(D("2"), D("0.001"), D("5")), tobin="0.001", spread="0.005"), "low")
    plan = {MON: [("A", "buy", "1")]}
    res = engine(Scripted(plan), {"A": series([10, 10, 10])}, capital="10000", c=c).run()
    (buy,) = [t for t in res.trades if t.side == "buy"]
    gross = buy.qty * 10
    assert c.fx_spread == 0 and c.tobin_rate == D("0.001")
    assert buy.costs_eur == max(gross * D("0.00025"), D("1")).quantize(D("0.01")) + gross * D("0.001")


def test_drawdown_brake_releases_after_a_year_in_cash():
    """Venduto tutto dopo il crollo, il freno non resta acceso per sempre: il massimo è quello degli ultimi 12 mesi."""
    d = days(400)
    data = {"A": series([10, 10] + [6] * 398)}

    class Watch(Scripted):
        def generate_decisions(self, ctx, ups, braking):
            self.seen = getattr(self, "seen", {})
            self.seen[ctx.today] = braking
            return super().generate_decisions(ctx, ups, braking)

    s = Watch({d[0]: [("A", "buy", "1")], d[3]: [("A", "sell", "0")], d[200]: [], d[398]: []})
    engine(s, data).run()
    assert s.seen[d[3]] is True and s.seen[d[200]] is True  # ancora entro i 12 mesi dal massimo
    assert s.seen[d[398]] is False


# ── Metriche ─────────────────────────────────────────────────────────────────

def test_metrics_cagr_and_drawdown():
    curve = [(date(2020, 1, 1), 100.0), (date(2020, 6, 1), 150.0), (date(2020, 9, 1), 75.0),
             (date(2021, 3, 1), 160.0), (date(2022, 1, 1), 200.0)]
    s = metrics.summary(curve, 0.02)
    assert abs(s["cagr"] - (2 ** (365.25 / 731) - 1)) < 1e-9
    assert abs(s["max_drawdown"] - (-0.5)) < 1e-12
    assert s["max_drawdown_peak"] == "2020-06-01" and s["max_drawdown_trough"] == "2020-09-01"
    assert s["longest_drawdown_days"] == (date(2021, 3, 1) - date(2020, 6, 1)).days


def test_metrics_drawdown_not_recovered():
    curve = [(date(2020, 1, 1), 100.0), (date(2020, 2, 1), 90.0), (date(2020, 12, 1), 95.0)]
    dd = metrics.max_drawdown(curve)
    assert dd["longest_days"] == 335 and dd["recovered"] is False


def test_weekly_keeps_last_day_of_each_week():
    curve = [(d, float(i)) for i, d in enumerate(days(10))]
    w = metrics.weekly(curve)
    assert [d.weekday() for d, _ in w] == [0, 4, 4]


# ── Coerenza con il vivo ─────────────────────────────────────────────────────

def test_costs_match_live_order_engine(db, account):
    inst = add_stock(db, "ENI.MI")
    c = load_costs(db)
    e = BacktestEngine(None, [], {"ENI.MI": it("ENI.MI")}, {}, {}, c, MON, MON, D("0"))
    for side in ("buy", "sell"):
        gross, comm, tobin = e._amounts(it("ENI.MI"), side, D("100"), D("13.5"), D("1"))
        p = PriceInfo(D("13.5"), None, "EUR", OPEN_MIL, "test", False)
        live = orders.compute(db, account, inst, side, D("100"), p, D("1"), OPEN_MIL)
        assert (gross, comm, tobin) == (live.gross_eur, live.commission_eur, live.tobin_tax_eur)


# ── Esecuzione completa con il database ──────────────────────────────────────

def test_execute_saves_results_and_trades(db):
    from .test_auto_a import _seed_universe
    symbols = ["AAA.MI", "BBB.MI"]
    _seed_universe(db, symbols, "test_univ")
    ds = days(300, date(2023, 1, 2))
    for i, sym in enumerate(symbols):
        add_stock(db, sym)
        for k, d in enumerate(ds):
            p = 10.0 + i + k * 0.01
            db.add(PriceHistoryCache(symbol=sym, date=d, open=p, high=p, low=p, close=p, volume=0,
                                     dividend=0.0, split_ratio=1.0))
    cfg = StrategyConfig(name="t", strategy_type="P1", params_json=json.dumps({"universe_list": "test_univ"}))
    db.add(cfg)
    db.commit()
    run = bt.BacktestRun(strategy_config_id=cfg.id, strategy_type="P1", strategy_version="1",
                         params_json=cfg.params_json, start_date=ds[0], end_date=ds[-1],
                         split_date=ds[150], initial_capital=D("10000"), status="running", progress=0)
    db.add(run)
    db.commit()
    bt.execute(db, run, fetch=False)

    assert run.status == "done"
    r = json.loads(run.results_json)
    assert set(r["periods"]) == {"full", "in_sample", "out_of_sample"}
    assert r["periods"]["full"]["strategy"]["cagr"] > 0
    assert any("ottimistico" in w for w in r["warnings"])
    assert db.query(BacktestTrade).filter_by(run_id=run.id, side="buy").count() >= 2
