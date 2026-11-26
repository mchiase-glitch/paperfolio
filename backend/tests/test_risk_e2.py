"""Fase E2: dimensionamento, limiti per titolo/settore/numero di titoli, stop facoltativi (vivo e backtest)."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import select

from app.models import Order, StrategyConfig, StrategyDecision
from app.services import auto_portfolio, risk
from app.services.backtest import Series
from app.services.price_history import DayRow
from app.services.strategies.base import BaseStrategy, Decision, StrategyContext, UniversePrice
from app.services.strategies.p4_momentum import P4Momentum
from app.services.strategies.p5_rsi2 import P5Rsi2

from .conftest import OPEN_MIL
from .test_auto_a import TODAY, _make_account, _ready_universe, no_background  # noqa: F401
from .test_backtest import days, engine, it


class Ctx(StrategyContext):
    """Contesto di prova: chiusure date per simbolo, quantità possedute."""

    def __init__(self, closes: dict[str, list[float]], qty: dict[str, D] | None = None, today=date(2025, 6, 2)):
        self.today = today
        self.data = {s: (days(len(c), today - timedelta(days=len(c) * 2)), c) for s, c in closes.items()}
        self.qty = qty or {}

    def quantity(self, symbol):
        return self.qty.get(symbol, D("0"))

    def cash(self):
        return D("0")

    def history(self, symbol, start, end):
        ds, cs = self.data.get(symbol, ([], []))
        return [DayRow(d, c, c * 1.01, c * 0.99, c, 0, 0.0, 1.0) for d, c in zip(ds, cs) if start <= d <= end]

    def history_count(self, symbol):
        return len(self.data.get(symbol, ([], []))[1])

    def closes(self, symbol):
        ds, cs = self.data.get(symbol, ([], []))
        return ds, cs, len(cs) - 1

    def entry_date(self, symbol):
        return None


def up(symbol, price="10", kind="stock"):
    return UniversePrice(symbol, None, D(price), "EUR", True, instrument_type=kind)


def wave(n, amp):
    """Prezzi che oscillano attorno a 100 di ±amp%: volatilità proporzionale ad amp."""
    return [100 * (1 + amp * (1 if i % 2 else -1)) for i in range(n)]


# ── Dimensionamento e limite per titolo ───────────────────────────────────────

def test_max_weight_caps_stocks_but_not_etfs_and_p5_default_is_20pct():
    ctx = Ctx({"A": [10.0] * 70})
    w, note = risk.sized_weight({}, D("0.10"), ctx, up("A"), D("0.5"), [up("A")])
    assert w == D("0.10") and "limitato" in note
    w, _ = risk.sized_weight({}, D("0.10"), ctx, up("ETF", kind="etf"), D("0.5"), [])
    assert w == D("0.5")
    assert P5Rsi2(None, {}).max_weight == D("0.20")
    assert P4Momentum(None, {}).max_weight == D("0.10")
    assert P4Momentum(None, {"max_weight": 0.15}).max_weight == D("0.15")


def test_inverse_volatility_weights_calm_stocks_more():
    ctx = Ctx({"CALM": wave(70, 0.01), "WILD": wave(70, 0.03)})
    universe = [up("CALM"), up("WILD")]
    p = {"sizing": "inverse_vol"}
    calm, note = risk.sized_weight(p, D("1"), ctx, universe[0], D("0.05"), universe)
    wild, _ = risk.sized_weight(p, D("1"), ctx, universe[1], D("0.05"), universe)
    # 1/σ: 3 a 1 → pesi 1,5 e 0,5 volte il normale (la media resta 5%)
    assert abs(float(calm) - 0.075) < 1e-4 and abs(float(wild) - 0.025) < 1e-4
    assert "volatilità" in note


def test_fixed_risk_uses_stop_distance_and_never_exceeds_normal_weight():
    ctx = Ctx({"A": [10.0] * 70})
    wide = {"sizing": "fixed_risk", "risk_per_trade": 0.01, "stop_fixed_pct": 0.20}
    w, note = risk.sized_weight(wide, D("1"), ctx, up("A"), D("0.10"), [up("A")])
    assert w == D("0.05") and "distanza dallo stop 20,0%" in note
    tight = {**wide, "stop_fixed_pct": 0.05}  # 1% / 5% = 20%, ma non oltre il 10% della strategia
    w, _ = risk.sized_weight(tight, D("1"), ctx, up("A"), D("0.10"), [up("A")])
    assert w == D("0.10")
    w, _ = risk.sized_weight({"sizing": "fixed_risk"}, D("1"), ctx, up("A"), D("0.10"), [up("A")])
    assert w == D("0.10")  # senza stop di prezzo resta il peso normale


# ── Stop ──────────────────────────────────────────────────────────────────────

def test_stop_level_takes_the_highest_of_the_active_stops():
    sp = risk.StopParams(fixed=D("0.10"), trailing=D("0.15"), atr_k=D("2"))
    level, why = risk.stop_level(sp, entry=100, highest=100, atr_entry=3)
    assert level == 94 and "volatilità" in why          # 100 − 2×3 sopra 90 (fisso) e 85 (trailing)
    level, why = risk.stop_level(sp, entry=100, highest=130, atr_entry=3)
    assert abs(level - 110.5) < 1e-9 and "trailing" in why  # 130 × 0,85
    assert risk.stop_level(risk.StopParams(), 100, 100, 3) is None


# ── Limiti sul portafoglio ────────────────────────────────────────────────────

def buy(sym, w="0.10"):
    return Decision(sym, "buy", D(w), f"compra {sym}")


def test_sector_limit_reduces_then_blocks_buys():
    ctx = Ctx({}, qty={"H": D("2500")})  # 25.000 € su 100.000: Banche al 25%
    universe = [up(s) for s in ("H", "B1", "B2", "T1")]
    sectors = {"H": "Banche", "B1": "Banche", "B2": "Banche", "T1": "Tecnologia"}
    out = risk.apply_limits({}, ctx, [buy("B1"), buy("B2"), buy("T1")], universe, D("100000"), sectors, D("2500"))
    by = {d.symbol: d for d in out}
    assert by["B1"].action == "buy" and abs(by["B1"].target_weight * D("0.98") - D("0.05")) < D("0.0001")
    assert "ridotto" in by["B1"].reason_it
    assert by["B2"].action == "hold" and "settore Banche" in by["B2"].reason_it
    assert by["T1"].target_weight == D("0.10")
    # limite disattivato (100%): nessun cambiamento
    assert risk.apply_limits({"max_sector": 1}, ctx, [buy("B2")], universe, D("100000"), sectors)[0].action == "buy"


def test_max_titles_counts_positions_being_sold():
    ctx = Ctx({}, qty={"H1": D("100"), "H2": D("100")})
    universe = [up(s) for s in ("H1", "H2", "N1", "N2")]
    decisions = [Decision("H1", "sell", D("0"), "esce"), buy("N1"), buy("N2")]
    out = risk.apply_limits({"max_titles": 2, "max_sector": 1}, ctx, decisions, universe, D("100000"), {})
    by = {d.symbol: d.action for d in out}
    assert by == {"H1": "sell", "N1": "buy", "N2": "hold"}


# ── Stop nel backtest ─────────────────────────────────────────────────────────

class BuyOnce(BaseStrategy):
    frequency = "daily"

    def __init__(self, day, params):
        super().__init__(None, {"max_weight": 1, **params})
        self.day = day

    def should_run_today(self, today, next_day=None):
        return today == self.day

    def generate_decisions(self, ctx, universe_prices, drawdown_braking):
        return [Decision("A.MI", "buy", D("1"), "compra")]


def rows(spec):
    """spec: [(open, high, low, close)] su giorni di borsa consecutivi."""
    return Series([DayRow(d, o, h, lo, c, 0, 0.0, 1.0) for d, (o, h, lo, c) in zip(days(len(spec)), spec)])


def test_backtest_fixed_stop_sells_at_level_or_at_open_on_gap():
    ds = days(5)
    data = {"A.MI": rows([(10, 10, 10, 10), (10, 10, 10, 10), (10, 10.2, 9.5, 9.8), (9.6, 9.7, 8.5, 9.0),
                          (9, 9, 9, 9)])}
    res = engine(BuyOnce(ds[0], {"stop_fixed_pct": 0.10}), data).run()
    sells = [t for t in res.trades if t.side == "sell"]
    assert len(sells) == 1 and sells[0].day == ds[3] and abs(sells[0].price - D("9")) < D("0.0001")
    assert "stop fisso" in sells[0].reason
    # apertura già sotto il livello: si vende all'apertura
    gap = {"A.MI": rows([(10, 10, 10, 10), (10, 10, 10, 10), (8, 8.2, 7.9, 8), (8, 8, 8, 8)])}
    s = [t for t in engine(BuyOnce(ds[0], {"stop_fixed_pct": 0.10}), gap).run().trades if t.side == "sell"]
    assert s[0].day == ds[2] and s[0].price == D("8")


def test_backtest_trailing_stop_follows_daily_highs():
    ds = days(6)
    data = {"A.MI": rows([(10, 10, 10, 10), (10, 10, 10, 10), (11, 12, 11, 12), (12, 12, 11.5, 11.8),
                          (11.5, 11.6, 10.5, 10.7), (10.7, 10.7, 10.7, 10.7)])}
    res = engine(BuyOnce(ds[0], {"stop_trailing_pct": 0.10}), data).run()
    sells = [t for t in res.trades if t.side == "sell"]
    # massimo 12 → livello 10,80: il minimo del 5° giorno (10,50) lo tocca
    assert sells[0].day == ds[4] and abs(sells[0].price - D("10.8")) < D("0.0001")


def test_backtest_time_stop_sells_after_n_days():
    ds = days(8)
    data = {"A.MI": rows([(10, 10, 10, 10)] * 8)}
    res = engine(BuyOnce(ds[0], {"stop_time_days": 3}), data).run()
    sells = [t for t in res.trades if t.side == "sell"]
    # comprato il 2° giorno; al 3° giorno di borsa successivo il segnale, vendita all'apertura dopo
    assert sells[0].day == ds[5] and "temporale" in sells[0].reason


def test_backtest_sector_limit_is_applied():
    ds = days(3)
    data = {s: rows([(10, 10, 10, 10)] * 3) for s in ("A.MI", "B.MI")}

    class BuyBoth(BuyOnce):
        def generate_decisions(self, ctx, universe_prices, drawdown_braking):
            return [Decision("A.MI", "buy", D("0.5"), "a"), Decision("B.MI", "buy", D("0.5"), "b")]

    e = engine(BuyBoth(ds[0], {}), data, capital="100000", instruments={s: it(s) for s in data})
    e.sectors = {"A.MI": "Banche", "B.MI": "Banche"}
    res = e.run()
    bought = sum(t.gross_eur for t in res.trades if t.side == "buy")
    assert abs(bought - D("30000")) < D("20")  # 30% del portafoglio sul settore


# ── Stop dal vivo ─────────────────────────────────────────────────────────────

def _cfg(db, params):
    cfg = StrategyConfig(name="P1 Stop", strategy_type="P1", is_paused=0, is_drawdown_braking=0,
                         params_json=json.dumps({"universe_list": "test_univ", "max_weight": 1, **params}))
    db.add(cfg)
    db.flush()
    return cfg


def run_and_stop(db, cfg):
    assert auto_portfolio.run_strategy(db, cfg, today=TODAY, now=OPEN_MIL)["orders"] == 2
    return auto_portfolio.manage_stops(db, cfg, auto_portfolio.make_strategy(cfg), today=TODAY, now=OPEN_MIL)


def test_live_protective_stop_is_placed_and_replaced_by_strategy_orders(db, provider, no_background):
    cfg = _cfg(db, {"stop_fixed_pct": 0.10})
    acc = _make_account(db, cfg, cash="10000")
    _ready_universe(db, provider)
    run_and_stop(db, cfg)  # compra, poi mette gli stop
    stops = db.scalars(select(Order).where(Order.account_id == acc.id, Order.status == "pending")).all()
    assert len(stops) == 2 and all(auto_portfolio.is_protective(o) for o in stops)
    assert all(o.order_type == "stop" and o.trigger_price == D("90") and o.side == "sell" for o in stops)
    log = db.scalars(select(StrategyDecision).where(StrategyDecision.reason_it.like("Ordine stop%"))).all()
    assert len(log) == 2

    # di nuovo lo stesso giorno: gli stop restano quelli, nessun doppione
    auto_portfolio.manage_stops(db, cfg, auto_portfolio.make_strategy(cfg), today=TODAY, now=OPEN_MIL)
    assert len(db.scalars(select(Order).where(Order.account_id == acc.id, Order.status == "pending")).all()) == 2

    # un ordine della strategia annulla lo stop del titolo e lo sostituisce
    inst_id = stops[0].instrument_id
    sym = db.get(__import__("app.models", fromlist=["Instrument"]).Instrument, inst_id).symbol
    p = auto_portfolio._build_universe_prices(db, [sym], TODAY)[0]
    oid, err = auto_portfolio._place_order(db, acc, cfg, Decision(sym, "sell", D("0"), "vendi"), p, D("10000"),
                                           OPEN_MIL)
    assert err is None and oid
    assert db.get(Order, stops[0].id).status == "cancelled"


def test_live_stops_switched_off_are_cancelled_and_trailing_uses_distance(db, provider, no_background):
    cfg = _cfg(db, {"stop_trailing_pct": 0.15})
    acc = _make_account(db, cfg, cash="10000")
    _ready_universe(db, provider)
    run_and_stop(db, cfg)
    pending = db.scalars(select(Order).where(Order.account_id == acc.id, Order.status == "pending")).all()
    assert all(o.order_type == "trailing_stop" and o.trailing_distance == D("15") for o in pending)
    assert all(o.trigger_price == D("85") for o in pending)

    cfg.params_json = json.dumps({**json.loads(cfg.params_json), "stop_trailing_pct": 0})
    db.commit()
    auto_portfolio.manage_stops(db, cfg, auto_portfolio.make_strategy(cfg), today=TODAY, now=OPEN_MIL)
    assert all(db.get(Order, o.id).status == "cancelled" for o in pending)


def test_live_time_stop_sells_at_market(db, provider, no_background):
    from app.services import positions
    cfg = _cfg(db, {"stop_time_days": 2})
    acc = _make_account(db, cfg, cash="10000")
    _ready_universe(db, provider)
    run_and_stop(db, cfg)
    assert positions.open_positions(db, acc.id)
    # lunedì successivo: tre giorni di borsa dopo l'acquisto di mercoledì
    later, now = TODAY + timedelta(days=5), OPEN_MIL + timedelta(days=5)
    from .test_auto_a import _seed_history_until
    for s in ("ENI.MI", "ISP.MI"):
        _seed_history_until(db, s, later, n_days=3)
        provider.set(s, "100", now)
    done = auto_portfolio.manage_stops(db, cfg, auto_portfolio.make_strategy(cfg), today=later, now=now)
    assert len(done) == 2 and all("temporale" in why for _, why in done)
    assert not [p for p in positions.open_positions(db, acc.id).values() if p.quantity > 0]


# ── API ───────────────────────────────────────────────────────────────────────

def test_api_defaults_and_validation():
    from fastapi import HTTPException
    from app.api.auto_portfolio import editable_defaults
    d = editable_defaults("P4")
    assert d["max_weight"] == 0.10 and d["max_sector"] == 0.30 and d["sizing"] == "equal"
    assert d["stop_time_days"] == 0 and list(d)[:3] == ["n_hold", "keep_rank", "trend_days"]
    assert editable_defaults("P5")["max_weight"] == 0.20
    assert "sizing" not in editable_defaults("P7") and editable_defaults("P7")["max_weight"] == 0.10
    assert math.isclose(editable_defaults("P1")["risk_per_trade"], 0.01)
    assert HTTPException  # import usato nel test dell'endpoint


def test_api_fixed_risk_requires_a_price_stop(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    app.dependency_overrides[get_db] = lambda: db
    try:
        cfg = _cfg(db, {})
        db.commit()
        c = TestClient(app)
        r = c.patch(f"/api/auto/{cfg.id}/params", json={"params": {"sizing": "fixed_risk"}})
        assert r.status_code == 400 and "stop" in r.json()["detail"]
        r = c.patch(f"/api/auto/{cfg.id}/params", json={"params": {"sizing": "fixed_risk", "stop_atr_k": 3,
                                                                    "max_titles": 0, "max_sector": 0.25}})
        assert r.status_code == 200
        assert r.json()["params"]["stop_atr_k"] == 3.0 and r.json()["params"]["max_sector"] == 0.25
        assert c.patch(f"/api/auto/{cfg.id}/params", json={"params": {"sizing": "boh"}}).status_code == 400
        assert c.patch(f"/api/auto/{cfg.id}/params", json={"params": {"max_sector": 0}}).status_code == 400
    finally:
        app.dependency_overrides.clear()
