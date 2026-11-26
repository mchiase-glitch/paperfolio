"""Regole di P6 (valore + qualità) e P7 (portafoglio combinato)."""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.auto_rules import order_quantity
from app.services.strategies.base import BaseStrategy, Decision, UniversePrice
from app.services.strategies.p6_value_quality import P6ValueQuality
from app.services.strategies.p7_combined import P7Combined

from .test_strategies_c import TODAY, Ctx, up


class FundCtx(Ctx):
    def __init__(self, *a, funds=None, **kw):
        super().__init__(*a, **kw)
        self.funds = funds or {}

    def fundamentals(self, symbol):
        return self.funds.get(symbol)


def fund(ebit, ev, ca=50.0, cl=30.0, ppe=80.0, industry="Auto Manufacturers", sector="Consumer Cyclical",
         ccy="EUR", fin="EUR"):
    return {"ebit": ebit, "enterprise_value": ev, "current_assets": ca, "current_liabilities": cl, "net_ppe": ppe,
            "gross_profit": 40.0, "total_assets": 500.0, "industry": industry, "sector": sector,
            "currency": ccy, "financial_currency": fin}


# ── P6 ───────────────────────────────────────────────────────────────────────

def test_p6_ranks_by_earnings_yield_plus_quality():
    funds = {
        "A.MI": fund(20, 100),   # rendimento 20%, redditività 20/100 = 20%  → primo in entrambe
        "B.MI": fund(10, 100),   # 10%, 10%
        "C.MI": fund(15, 300),   # 5%, 15%
        "D.MI": fund(1, 100),    # 1%, 1%
    }
    ctx = FundCtx({}, TODAY, funds=funds)
    dec = {d.symbol: d for d in P6ValueQuality(None, {"n_hold": 2}).generate_decisions(
        ctx, [up(s, 10) for s in funds], False)}
    assert {s for s, d in dec.items() if d.action == "buy"} == {"A.MI", "B.MI"}
    assert dec["A.MI"].target_weight == D("0.5")
    assert "1° in classifica" in dec["A.MI"].reason_it


def test_p6_excludes_financials_utilities_and_missing_data():
    funds = {
        "BANK.MI": fund(50, 100, industry="Banks - Regional", sector="Financial Services"),
        "INS.MI": fund(50, 100, industry="Insurance - Diversified", sector="Financial Services"),
        "UTIL.MI": fund(50, 100, industry="Utilities - Regulated Electric", sector="Utilities"),
        "NOEV.MI": fund(50, None),
        "OK.MI": fund(5, 100),
    }
    ctx = FundCtx({}, TODAY, funds=funds)
    dec = {d.symbol: d for d in P6ValueQuality(None, {"n_hold": 5}).generate_decisions(
        ctx, [up(s, 10) for s in [*funds, "NODATA.MI"]], False)}
    assert dec["OK.MI"].action == "buy"
    assert "banca" in dec["BANK.MI"].reason_it and "assicurazione" in dec["INS.MI"].reason_it
    assert "utility" in dec["UTIL.MI"].reason_it
    assert dec["NOEV.MI"].action == "skip" and dec["NODATA.MI"].action == "skip"


def test_p6_sells_holdings_out_of_top_and_runs_once_a_year_in_its_month():
    funds = {"A.MI": fund(20, 100), "B.MI": fund(1, 100)}
    ctx = FundCtx({}, TODAY, funds=funds, cash="1000", holdings={"B.MI": "10"})
    dec = {d.symbol: d.action for d in P6ValueQuality(None, {"n_hold": 1}).generate_decisions(
        ctx, [up(s, 10) for s in funds], False)}
    assert dec == {"A.MI": "buy", "B.MI": "sell"}
    s = P6ValueQuality(None, {"rebalance_month": 4})
    from datetime import date
    assert s.should_run_today(date(2026, 4, 1)) and not s.should_run_today(date(2026, 5, 4))
    assert s.backtest_unavailable


def test_p6_converts_ebit_currency_to_listing_currency():
    """Bilancio in dollari, quotazione in euro: l'EBIT si converte prima di dividerlo per il valore d'impresa."""
    funds = {"STM.MI": fund(110, 1000, ccy="EUR", fin="USD"), "X.MI": fund(105, 1000)}
    ctx = FundCtx({"EURUSD=X": [1.1] * 300}, TODAY, funds=funds)
    dec = P6ValueQuality(None, {"n_hold": 2}).generate_decisions(ctx, [up(s, 10) for s in funds], False)
    stm = next(d for d in dec if d.symbol == "STM.MI")
    assert abs(stm.signal_data["ey"] - 0.1) < 1e-9  # 110 USD = 100 EUR su 1000 EUR


# ── P7 ───────────────────────────────────────────────────────────────────────

class Scripted(BaseStrategy):
    frequency = "daily"

    def __init__(self, decisions):
        super().__init__(None, {})
        self.decisions = decisions

    def should_run_today(self, today, next_day=None):
        return True

    def generate_decisions(self, ctx, ups, braking):
        return list(self.decisions)


def p7(sleeves, state=None, **params):
    s = P7Combined(None, {"sleeves": [], **params})
    s.sleeves = [(name, strat, D(str(share))) for name, strat, share in sleeves]
    s.state = state or {}
    return s


def test_p7_nets_opposite_orders_on_same_stock():
    """Una quota compra 100 ENI, l'altra ne vende 60: parte un solo acquisto da 40."""
    buyer = Scripted([Decision("ENI.MI", "buy", D("1000") / D("4900"), "compra")])
    seller = Scripted([Decision("ENI.MI", "sell", D("0"), "vende")])
    state = {"books": {"A": {"cash": "5000", "qty": {}}, "B": {"cash": "4400", "qty": {"ENI.MI": "60"}}},
             "rebalanced_year": TODAY.year}
    s = p7([("A", buyer, 0.5), ("B", seller, 0.5)], state)
    ctx = Ctx({}, TODAY, cash="9400", holdings={"ENI.MI": "60"})
    dec = [d for d in s.generate_decisions(ctx, [up("ENI.MI", 10)], False) if d.action in ("buy", "sell")]
    assert len(dec) == 1 and dec[0].action == "buy"
    qty, _ = order_quantity("buy", dec[0].target_weight, D("60"), D("60"), D("10"), D("10000"))
    assert qty == 40
    assert "Ordine netto: acquisto di 40" in dec[0].reason_it
    assert s.state["books"]["A"]["qty"]["ENI.MI"] == "100" and "ENI.MI" not in s.state["books"]["B"]["qty"]


def test_p7_reconciles_books_with_real_portfolio():
    """Ordine eseguito solo in parte e commissioni: le quote si riallineano al portafoglio vero."""
    state = {"books": {"A": {"cash": "0", "qty": {"X.MI": "60"}}, "B": {"cash": "400", "qty": {"X.MI": "40"}}},
             "rebalanced_year": TODAY.year}
    s = p7([("A", Scripted([]), 0.5), ("B", Scripted([]), 0.5)], state)
    ctx = Ctx({}, TODAY, cash="390", holdings={"X.MI": "50"})
    s.generate_decisions(ctx, [up("X.MI", 10)], False)
    books = s.state["books"]
    assert books["A"]["qty"]["X.MI"] == "30" and books["B"]["qty"]["X.MI"] == "20"
    assert sum(D(b["cash"]) for b in books.values()) == D("390")


def test_p7_unfilled_buy_refunds_the_sleeve_that_asked():
    """Acquisto della quota A non eseguito: la liquidità torna ad A, non viene divisa con B."""
    state = {"books": {"A": {"cash": "0", "qty": {"X.MI": "100"}}, "B": {"cash": "1000", "qty": {}}},
             "rebalanced_year": TODAY.year}
    s = p7([("A", Scripted([]), 0.5), ("B", Scripted([]), 0.5)], state)
    s.generate_decisions(Ctx({}, TODAY, cash="2000"), [up("X.MI", 10)], False)
    books = s.state["books"]
    assert "X.MI" not in books["A"]["qty"]
    assert D(books["A"]["cash"]) == D("1000") and D(books["B"]["cash"]) == D("1000")


def test_p7_caps_single_stock_weight():
    buyer = Scripted([Decision("X.MI", "buy", D("1"), "tutto su X")])
    s = p7([("A", buyer, 1.0)], {"books": {"A": {"cash": "10000", "qty": {}}}, "rebalanced_year": TODAY.year})
    ctx = Ctx({}, TODAY, cash="10000")
    (d,) = [d for d in s.generate_decisions(ctx, [up("X.MI", 10)], False) if d.action == "buy"]
    qty, _ = order_quantity("buy", d.target_weight, D("0"), D("0"), D("10"), D("10000"))
    assert qty == 100 and "Limitato a 10%" in d.reason_it


def test_p7_yearly_rebalance_of_shares():
    from datetime import date
    state = {"books": {"A": {"cash": "7000", "qty": {}}, "B": {"cash": "3000", "qty": {}}}, "rebalanced_year": 2025}
    s = p7([("A", Scripted([]), 0.5), ("B", Scripted([]), 0.5)], state, rebalance_month=TODAY.month)
    s.generate_decisions(Ctx({}, TODAY, cash="10000"), [], False)
    assert s.state["books"]["A"]["cash"] == "5000.00" and s.state["books"]["B"]["cash"] == "5000.00"
    assert s.state["rebalanced_year"] == TODAY.year


def test_min_order_skips_small_rebalancing_only():
    m = D("2500")
    # Ribilanciamento di 100 azioni a 10 € = 1.000 €: sotto il minimo, non si fa
    qty, err = order_quantity("buy", D("0.5"), D("390"), D("390"), D("10"), D("10000"), m)
    assert qty == 0 and "ordine minimo" in err
    qty, err = order_quantity("sell", D("0.3"), D("400"), D("400"), D("10"), D("10000"), m)
    assert qty == 0 and "ordine minimo" in err
    # Posizione nuova e vendita totale si fanno sempre, anche se piccole
    assert order_quantity("buy", D("0.1"), D("0"), D("0"), D("10"), D("10000"), m)[0] == 98
    assert order_quantity("sell", D("0"), D("50"), D("50"), D("10"), D("10000"), m)[0] == 50
    # Sopra la soglia il ribilanciamento parte
    assert order_quantity("buy", D("0.5"), D("100"), D("100"), D("10"), D("10000"), m)[0] == 390


def test_edit_and_reset_params_via_api(provider, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import auto_portfolio
    monkeypatch.setattr(auto_portfolio, "start_preparation", lambda ss, *a: True)
    with TestClient(app) as client:
        cfg = client.post("/api/auto", json={"name": "Mix", "strategy_type": "P7", "initial_capital": 50000}).json()
        assert cfg["defaults"]["min_order"] == 2500 and cfg["defaults"]["drawdown_brake"] is True
        url = f"/api/auto/{cfg['id']}/params"
        r = client.patch(url, json={"params": {"max_weight": 0.15, "min_order": 1000, "drawdown_brake": False},
                                    "sleeve_shares": [3, 1]})
        assert r.status_code == 200, r.text
        p = r.json()["params"]
        assert p["max_weight"] == 0.15 and p["min_order"] == 1000 and p["drawdown_brake"] is False
        assert [s["share"] for s in p["sleeves"]] == [0.75, 0.25]
        assert client.patch(url, json={"params": {"max_weight": 2}}).status_code == 400
        assert client.patch(url, json={"params": {"universe_list": "sp100"}}).status_code == 400
        assert client.patch(url, json={"sleeve_shares": [1]}).status_code == 400
        p = client.patch(url, json={"reset": True}).json()["params"]
        assert p["max_weight"] == 0.10 and p["min_order"] == 2500 and p["drawdown_brake"] is True
        assert [s["share"] for s in p["sleeves"]] == [0.5, 0.5]
        assert [s["type"] for s in p["sleeves"]] == ["P2", "P4"]


def test_next_check_skips_done_periods_and_pause(db, account):
    import json
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    from app.models import StrategyConfig, StrategyRun
    from app.services import auto_portfolio
    rome = ZoneInfo("Europe/Rome")
    now = datetime(2025, 3, 3, 18, 0, tzinfo=rome)  # lunedì, dopo il controllo delle 17

    def cfg(stype, params):
        c = StrategyConfig(name=stype, strategy_type=stype, params_json=json.dumps(params), is_paused=0)
        db.add(c)
        db.commit()
        return c, auto_portfolio.make_strategy(c)

    def at(c, s):
        return auto_portfolio.next_check(db, c, s, now).astimezone(rome).replace(tzinfo=None)

    c5, s5 = cfg("P5", {})
    assert at(c5, s5) == datetime(2025, 3, 4, 17, 0)
    db.add(StrategyRun(strategy_config_id=c5.id, account_id=account.id, run_key=s5.run_key(date(2025, 3, 4)),
                       status="ok", is_dry_run=0))
    db.commit()
    assert at(c5, s5) == datetime(2025, 3, 5, 17, 0)
    c2, s2 = cfg("P2", {"universe_list": "ftse_mib"})
    assert at(c2, s2) == datetime(2025, 3, 31, 17, 0)  # ultimo giorno di borsa del mese
    c1, s1 = cfg("P1", {"universe_list": "sp100"})
    assert at(c1, s1) == datetime(2025, 3, 3, 21, 30)  # solo USA: controllo serale, oggi
    c1.is_paused = 1
    assert auto_portfolio.next_check(db, c1, s1, now) is None


def test_min_order_is_a_common_parameter():
    assert P6ValueQuality(None, {}).min_order == D("2500")
    assert P6ValueQuality(None, {"min_order": 0}).min_order == 0


def test_p7_default_sleeves_and_union_of_universes():
    s = P7Combined(None, {})
    assert [n for n, _, _ in s.sleeves] == ["P2", "P4"]
    assert set(s.universe_lists()) == {"ftse_mib", "eurostoxx50", "sp100"}
    assert s.backtest_unavailable is None
    with_p6 = P7Combined(None, {"sleeves": [{"type": "P1", "params": {"universe_list": "ftse_mib"}},
                                            {"type": "P6"}]})
    assert with_p6.backtest_unavailable and with_p6.needs_fundamentals


def test_p7_sleeve_sees_only_its_own_universe():
    from app.services.strategies.p1_buy_hold import P1BuyHold
    s = p7([("A", P1BuyHold(None, {"universe_list": "ftse_mib"}), 1.0)],
           {"books": {"A": {"cash": "10000", "qty": {}}}, "rebalanced_year": TODAY.year}, max_weight=1)
    ups = [up("ENI.MI", 10, groups=["ftse_mib"]), up("AAPL", 10, market="USA", groups=["sp100"])]
    dec = s.generate_decisions(Ctx({}, TODAY, cash="10000"), ups, False)
    assert [(d.symbol, d.action) for d in dec if d.action == "buy"] == [("ENI.MI", "buy")]


def test_p7_in_backtest_executes_one_netted_order_per_stock():
    from app.services.backtest import BacktestEngine
    from .test_backtest import costs, engine, series
    data = {"A": series([10] * 5), "B": series([20] * 5)}
    s = P7Combined(None, {"sleeves": [{"type": "P1", "share": 0.5, "params": {}},
                                      {"type": "P1", "share": 0.5, "params": {}}], "max_weight": 1})
    res = engine(s, data).run()
    buys = [t for t in res.trades if t.side == "buy"]
    # Ogni quota da 500 € compra 24 A (500 × 50% × 98% / 10): un solo ordine da 48
    assert sorted((t.symbol, t.qty) for t in buys) == [("A", 48), ("B", 24)]
    assert res.final_value == D("1000")


def test_p6_backtest_refused(db):
    import json
    from datetime import date
    from app.services import backtest
    run = backtest.BacktestRun(strategy_type="P6", strategy_version="1", params_json=json.dumps({}),
                               start_date=date(2015, 1, 1), end_date=date(2020, 1, 1),
                               initial_capital=D("1000"), status="running", progress=0)
    db.add(run)
    db.commit()
    with pytest.raises(ValueError, match="bilanci"):
        backtest.execute(db, run, fetch=False)
