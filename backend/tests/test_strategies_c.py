"""Regole di P3 (dual momentum), P4 (momentum 12-1 con filtro) e P5 (RSI a 2 giorni) su dati costruiti a mano."""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal as D

from app.services import indicators
from app.services.strategies.base import StrategyContext, UniversePrice
from app.services.strategies.p3_dual_momentum import P3DualMomentum
from app.services.strategies.p4_momentum import P4Momentum
from app.services.strategies.p5_rsi2 import P5Rsi2

START = date(2023, 1, 2)


def weekdays(n, start=START):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def path(n, start=100.0, daily=0.0, tail=None):
    """Serie a crescita costante, con eventuali ultimi valori sostituiti."""
    out, p = [], start
    for _ in range(n):
        out.append(p)
        p *= 1 + daily
    if tail:
        out[-len(tail):] = tail
    return out


class Ctx(StrategyContext):
    def __init__(self, series, today, cash="100000", holdings=None, entries=None):
        self.series = {s: (weekdays(len(c)), c) for s, c in series.items()}
        self.today = today
        self._cash = D(cash)
        self._holdings = {k: D(v) for k, v in (holdings or {}).items()}
        self._entries = entries or {}

    def quantity(self, symbol):
        return self._holdings.get(symbol, D("0"))

    def cash(self):
        return self._cash

    def history(self, symbol, start, end):
        return []

    def history_count(self, symbol):
        return self.closes(symbol)[2] + 1

    def closes(self, symbol):
        dates, closes = self.series.get(symbol, ([], []))
        return dates, closes, bisect_right(dates, self.today) - 1

    def entry_date(self, symbol):
        return self._entries.get(symbol)


def up(symbol, price, market="ITA", groups=(), itype="stock", ccy="EUR"):
    return UniversePrice(symbol, None, D(str(price)), "EUR", True, market, tuple(groups), itype, ccy)


N = 300
TODAY = weekdays(N)[-1]
FX = {"EURUSD=X": [1.0] * N}


# ── Indicatori ────────────────────────────────────────────────────────────────

def test_rsi_series_matches_single_value():
    closes = [10, 11, 10.5, 10.2, 10.8, 11.5, 11.1, 10.7, 10.9, 11.4]
    series = indicators.rsi_series(closes, 2)
    for k in range(4, len(closes) + 1):
        assert abs(series[k - 1] - indicators.rsi(closes[:k], 2)) < 1e-9


# ── P3 ───────────────────────────────────────────────────────────────────────

def p3_series(ita, eur, usa, extra=None):
    s = {"FTSEMIB.MI": path(N, 100, ita), "^STOXX50E": path(N, 100, eur), "^GSPC": path(N, 100, usa), **FX}
    s.update(extra or {})
    return s


def test_p3_goes_to_best_region_etf_and_top_stocks():
    stocks = {f"S{i}.MI": path(N, 10, 0.0002 * i) for i in range(1, 13)}
    ctx = Ctx(p3_series(0.001, 0.0005, -0.0005, stocks), TODAY)
    ups = [up("IMIB.MI", 30, itype="etf"), up("XGLE.MI", 200, itype="etf")] + \
          [up(s, c[-1], groups=["ftse_mib"]) for s, c in stocks.items()]
    dec = {d.symbol: d for d in P3DualMomentum(None, {"n_stocks": 10}).generate_decisions(ctx, ups, False)}
    assert dec["IMIB.MI"].action == "buy" and dec["IMIB.MI"].target_weight == D("0.5")
    bought = {s for s, d in dec.items() if d.action == "buy" and s != "IMIB.MI"}
    assert bought == {f"S{i}.MI" for i in range(3, 13)}  # i 10 con il momentum più alto
    assert all(dec[s].target_weight == D("0.05") for s in bought)
    assert "XGLE.MI" not in dec


def test_p3_refuge_when_no_region_beats_threshold():
    ctx = Ctx(p3_series(-0.001, -0.0005, -0.0002), TODAY, cash="50000", holdings={"IMIB.MI": "1000"})
    ups = [up("IMIB.MI", 50, itype="etf"), up("XGLE.MI", 200, itype="etf")]
    dec = {d.symbol: d for d in P3DualMomentum(None, {}).generate_decisions(ctx, ups, False)}
    assert dec["XGLE.MI"].action == "buy" and dec["XGLE.MI"].target_weight == 1
    assert dec["IMIB.MI"].action == "sell" and dec["IMIB.MI"].target_weight == 0


def test_p3_refuge_cash_only_sells():
    ctx = Ctx(p3_series(-0.001, -0.0005, -0.0002), TODAY, cash="50000", holdings={"IMIB.MI": "1000"})
    ups = [up("IMIB.MI", 50, itype="etf"), up("XGLE.MI", 200, itype="etf")]
    decisions = P3DualMomentum(None, {"refuge": "cash"}).generate_decisions(ctx, ups, False)
    assert [(d.symbol, d.action) for d in decisions if d.symbol != "—"] == [("IMIB.MI", "sell")]


def test_p3_uses_euro_returns():
    """S&P in dollari sale del 10%, ma il dollaro perde il 20%: in euro la regione USA perde."""
    fx = path(N, 1.0, 0.0, tail=None)
    fx = [1.0] * (N - 1) + [1.25]
    s = p3_series(0.0001, 0.0001, 0.0)
    s["^GSPC"] = [100.0] * (N - 1) + [110.0]
    s["EURUSD=X"] = fx
    ctx = Ctx(s, TODAY)
    ups = [up("IMIB.MI", 30, itype="etf"), up("MSE.MI", 60, itype="etf"), up("IUSA.MI", 60, itype="etf")]
    dec = {d.symbol: d.action for d in P3DualMomentum(None, {"etf_share": 1}).generate_decisions(ctx, ups, False)}
    assert dec.get("IUSA.MI") is None and "buy" in (dec.get("IMIB.MI"), dec.get("MSE.MI"))


# ── P4 ───────────────────────────────────────────────────────────────────────

def p4_ctx(n_stocks, index_up=True, holdings=None):
    stocks = {f"S{i:02d}.MI": path(N, 10, 0.0001 * i) for i in range(1, n_stocks + 1)}
    idx = path(N, 100, 0.001 if index_up else -0.001)
    series = {"FTSEMIB.MI": idx, "^STOXX50E": idx, "^GSPC": idx, **FX, **stocks}
    return Ctx(series, TODAY, holdings=holdings), [up(s, c[-1]) for s, c in stocks.items()]


def test_p4_buys_top_ten_when_trend_up():
    ctx, ups = p4_ctx(25)
    dec = P4Momentum(None, {}).generate_decisions(ctx, ups, False)
    buys = {d.symbol for d in dec if d.action == "buy"}
    assert buys == {f"S{i:02d}.MI" for i in range(16, 26)}
    assert all(d.target_weight == D("0.1") for d in dec if d.action == "buy")


def test_p4_hysteresis_keeps_top_twenty_and_sells_the_rest():
    # S07 è 19° su 25: resta. S03 è 23°: esce.
    ctx, ups = p4_ctx(25, holdings={"S07.MI": "100", "S03.MI": "100"})
    dec = {d.symbol: d.action for d in P4Momentum(None, {}).generate_decisions(ctx, ups, False)}
    assert dec["S07.MI"] == "hold" and dec["S03.MI"] == "sell"
    assert sum(1 for a in dec.values() if a == "buy") == 9  # un posto è occupato da S07


def test_p4_trend_filter_leaves_slot_in_cash():
    ctx, ups = p4_ctx(25, index_up=False)
    dec = P4Momentum(None, {}).generate_decisions(ctx, ups, False)
    assert not [d for d in dec if d.action == "buy"]
    assert all("sotto la media a 200" in d.reason_it for d in dec)


# ── P5 ───────────────────────────────────────────────────────────────────────

def dip(n=N):
    """Lunga salita, poi tre giorni di calo deciso: sopra la media a 200, RSI(2) molto basso."""
    s = path(n, 50, 0.002)
    s[-3:] = [s[-4] * 0.97, s[-4] * 0.94, s[-4] * 0.91]
    return s


def test_p5_buys_dip_in_uptrend():
    ctx = Ctx({"A.MI": dip(), "B.MI": path(N, 50, 0.002)}, TODAY)
    dec = {d.symbol: d for d in P5Rsi2(None, {}).generate_decisions(ctx, [up("A.MI", 1), up("B.MI", 1)], False)}
    assert dec["A.MI"].action == "buy" and dec["A.MI"].target_weight == D("0.2")
    assert "B.MI" not in dec  # nessun calo: nessun segnale


def test_p5_no_buy_below_long_average():
    falling = path(N, 100, -0.002)
    falling[-3:] = [falling[-4] * 0.97, falling[-4] * 0.94, falling[-4] * 0.91]
    ctx = Ctx({"A.MI": falling}, TODAY)
    assert P5Rsi2(None, {}).generate_decisions(ctx, [up("A.MI", 1)], False) == []


def test_p5_exit_on_rebound_and_time_stop():
    rebound = dip()
    rebound[-1] = rebound[-5] * 1.02  # torna sopra la media a 5 giorni
    days = weekdays(N)
    ctx = Ctx({"R.MI": rebound, "T.MI": dip()}, TODAY, holdings={"R.MI": "10", "T.MI": "10"},
              entries={"R.MI": days[-3], "T.MI": days[-12]})
    dec = {d.symbol: d for d in P5Rsi2(None, {}).generate_decisions(ctx, [up("R.MI", 1), up("T.MI", 1)], False)}
    assert dec["R.MI"].action == "sell" and "rimbalzo" in dec["R.MI"].reason_it
    assert dec["T.MI"].action == "sell" and "stop temporale" in dec["T.MI"].reason_it


def test_p5_max_positions_lowest_rsi_first():
    series = {f"D{i}.MI": dip() for i in range(7)}
    for i in range(7):  # cali via via più forti: RSI più basso per i numeri alti
        s = series[f"D{i}.MI"]
        s[-1] = s[-4] * (0.91 - 0.01 * i)
    held = {"H.MI": path(N, 50, 0.002, tail=None)}
    held["H.MI"][-1] = held["H.MI"][-6] * 0.999  # sotto la media a 5: si tiene
    ctx = Ctx({**series, **held}, TODAY, holdings={"H.MI": "10"}, entries={"H.MI": weekdays(N)[-2]})
    ups = [up(s, 1) for s in [*series, "H.MI"]]
    dec = P5Rsi2(None, {}).generate_decisions(ctx, ups, False)
    buys = [d.symbol for d in dec if d.action == "buy"]
    assert len(buys) == 4 and set(buys) == {"D6.MI", "D5.MI", "D4.MI", "D3.MI"}


def test_session_and_symbols_by_strategy(db):
    from app.services import auto_portfolio
    from app.services.strategies.p1_buy_hold import P1BuyHold
    from app.services.universes import seed_universes
    seed_universes(db)
    us_only = P1BuyHold(None, {"universe_list": "sp100"})
    assert auto_portfolio.strategy_region(us_only) == "US"
    # Titoli europei e americani insieme: gira alle 17, con entrambe le borse aperte
    assert auto_portfolio.strategy_region(P4Momentum(None, {})) == "EU"
    ss = auto_portfolio.strategy_symbols(db, P3DualMomentum(None, {}))
    assert {"IMIB.MI", "MSE.MI", "IUSA.MI", "XGLE.MI"} <= set(ss.tradeable)
    assert set(ss.reference) == {"FTSEMIB.MI", "^STOXX50E", "^GSPC", "EURUSD=X"}
    assert "ftse_mib" in ss.groups["ENI.MI"]


def test_create_multi_list_portfolio_via_api(provider, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import auto_portfolio
    started = []
    monkeypatch.setattr(auto_portfolio, "start_preparation", lambda ss: started.append(ss.key) or True)
    with TestClient(app) as client:
        r = client.post("/api/auto", json={"name": "Momentum", "strategy_type": "P4", "initial_capital": 50000})
        assert r.status_code == 201, r.text
        cfg = r.json()
        assert cfg["universe_lists"] == ["ftse_mib", "eurostoxx50", "sp100"]
        assert cfg["params"]["n_hold"] == 10 and "universe_list" not in cfg["params"]
        assert cfg["session"] == "EU" and started
        assert client.post("/api/auto", json={"name": "x", "strategy_type": "P1",
                                              "initial_capital": 1000}).status_code == 400


def test_backtest_time_stop_uses_entry_day():
    """Nel backtest il giorno di apertura della posizione è quello dell'esecuzione: lo stop temporale lo usa."""
    from app.services.backtest import BacktestContext, BacktestEngine, Holding, Series
    from app.services.price_history import DayRow
    ds = weekdays(30)
    s = Series([DayRow(d, 10, 10, 10, 10, 0, 0.0, 1.0) for d in ds])
    e = BacktestEngine(None, ["A"], {}, {"A": s}, {}, None, ds[0], ds[-1], D("0"))
    e.holdings["A"] = Holding(D("5"), opened=ds[3])
    assert BacktestContext(e, ds[13]).held_days("A") == 10
    assert BacktestContext(e, ds[3]).held_days("A") == 0


def test_p5_drawdown_brake_blocks_entries():
    ctx = Ctx({"A.MI": dip()}, TODAY)
    dec = P5Rsi2(None, {}).generate_decisions(ctx, [up("A.MI", 1)], True)
    assert [d.action for d in dec] == ["hold"]
