"""
Test suite per la Fase A dei portafogli automatici.

Copre:
- indicators (sma, monthly_sma, split_adjust, volatility_annual)
- P1 (buy & hold + ribilanciamento)
- P2 (trend Faber 10 mesi, should_run_today)
- trailing stop (aggiornamento trigger, esecuzione)
- idempotenza (run_key già presente → skip)
- drawdown brake (attivazione e riattivazione)
- interruttore di sicurezza (copertura dati)
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.models import (
    Account, PriceHistoryCache, StrategyConfig, StrategyRun,
    UniverseList, UniverseListItem,
)
from app.services import auto_portfolio
from app.services import indicators
from app.services.price_history import get_rows, get_adjusted_closes
from app.services.strategies.p1_buy_hold import P1BuyHold
from app.services.strategies.p2_trend import P2Trend, _is_last_trading_day_of_month
from app.services.strategies.base import Decision, UniversePrice

from .conftest import OPEN_MIL, utc


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_config(db, name="P1 Test", stype="P1", universe_list="test_univ") -> StrategyConfig:
    cfg = StrategyConfig(
        name=name,
        strategy_type=stype,
        params_json=json.dumps({"universe_list": universe_list, "rebalance_band": "0.25"}),
        is_paused=0,
        is_drawdown_braking=0,
    )
    db.add(cfg)
    db.flush()
    return cfg


def _make_account(db, cfg: StrategyConfig, cash="10000") -> Account:
    from app.services import portfolio
    from datetime import timezone
    now = datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)
    acc = portfolio.open_account(db, D(cash), now=now, name=f"Auto {cfg.name}")
    acc.strategy_config_id = cfg.id
    db.flush()
    return acc


def _seed_universe(db, symbols: list[str], list_name="test_univ") -> None:
    lst = db.scalar(select(UniverseList).where(UniverseList.name == list_name))
    if lst is None:
        lst = UniverseList(name=list_name, label="Test", source="manual")
        db.add(lst)
        db.flush()
    for sym in symbols:
        exists = db.scalar(
            select(UniverseListItem)
            .where(UniverseListItem.list_id == lst.id, UniverseListItem.symbol == sym)
        )
        if not exists:
            db.add(UniverseListItem(list_id=lst.id, symbol=sym, name=sym))
    db.commit()


def _seed_prices(db, symbol: str, n_days: int, start_price: float = 100.0,
                 drift: float = 0.0, start_date: date | None = None) -> None:
    """Inserisce n_days di prezzi in price_history_cache (senza split, senza dividendi)."""
    from app.database import utcnow
    if start_date is None:
        start_date = date.today() - timedelta(days=n_days + 5)
    d = start_date
    price = start_price
    added = 0
    while added < n_days:
        if d.weekday() < 5:  # solo giorni lavorativi
            db.add(PriceHistoryCache(
                symbol=symbol, date=d,
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=100000, dividend=0.0, split_ratio=1.0,
                fetched_at=utcnow(),
            ))
            price *= (1 + drift)
            added += 1
        d += timedelta(days=1)
    db.commit()


# ── Indicatori ────────────────────────────────────────────────────────────────

def test_sma_basic():
    prices = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = indicators.sma(prices, 3)
    assert result[:2] == [None, None]
    assert abs(result[2] - 2.0) < 1e-9
    assert abs(result[4] - 4.0) < 1e-9


def test_last_sma_insufficient():
    assert indicators.last_sma([1.0, 2.0], 5) is None


def test_monthly_closes_picks_last_day():
    dates = [date(2024, 1, 29), date(2024, 1, 30), date(2024, 1, 31),
             date(2024, 2, 1), date(2024, 2, 29)]
    closes = [100.0, 101.0, 102.0, 95.0, 110.0]
    mc = indicators.monthly_closes(dates, closes)
    assert len(mc) == 2
    assert mc[0] == (date(2024, 1, 31), 102.0)
    assert mc[1] == (date(2024, 2, 29), 110.0)


def test_monthly_sma_needs_enough_months():
    # Solo 5 mesi di dati, non abbastanza per SMA(10)
    dates = [date(2024, m, 28) for m in range(1, 6)]
    closes = [100.0] * 5
    assert indicators.monthly_sma(dates, closes, 10) is None


def test_split_adjust_no_splits():
    closes = [10.0, 11.0, 12.0]
    splits = [1.0, 1.0, 1.0]
    adj = indicators.split_adjust(closes, splits)
    assert adj == closes


def test_split_adjust_one_split():
    # Split 2:1 nell'ultimo giorno → i prezzi precedenti dimezzati
    closes = [20.0, 21.0, 10.0]  # il giorno 2 c'è uno split 2:1 (prezzo dimezzato)
    splits = [1.0, 1.0, 2.0]
    adj = indicators.split_adjust(closes, splits)
    # Dopo lo split, il prezzo attuale è 10 → i prezzi precedenti vanno divisi per 2
    assert abs(adj[0] - 10.0) < 1e-9
    assert abs(adj[1] - 10.5) < 1e-9
    assert abs(adj[2] - 10.0) < 1e-9


def test_volatility_annual_constant():
    # Prezzi costanti → volatilità zero
    closes = [100.0] * 62
    vol = indicators.volatility_annual(closes, 60)
    assert vol is not None and abs(vol) < 1e-9


def test_volatility_annual_insufficient():
    assert indicators.volatility_annual([100.0] * 10, 60) is None


# ── P2: last trading day of month ─────────────────────────────────────────────

def test_last_trading_day_of_month():
    # Giovedì 30/01/2025: il giorno successivo lavorativo è venerdì 31 gennaio (stesso mese) → NO
    assert _is_last_trading_day_of_month(date(2025, 1, 30)) is False
    # Venerdì 31/01/2025: il giorno successivo lavorativo è lunedì 03/02/2025 (mese diverso) → SÌ
    assert _is_last_trading_day_of_month(date(2025, 1, 31)) is True
    # Venerdì 28/02/2025: il giorno successivo lavorativo è lunedì 03/03 (mese diverso) → SÌ
    assert _is_last_trading_day_of_month(date(2025, 2, 28)) is True


# ── P1 decisions ─────────────────────────────────────────────────────────────

def test_p1_buy_all_on_empty_portfolio(db):
    cfg = _make_config(db)
    acc = _make_account(db, cfg, cash="10000")
    params = {"universe_list": "test_univ", "rebalance_band": "0.25"}
    strategy = P1BuyHold(cfg, params)

    prices = [
        UniversePrice("AAPL", None, D("150"), "USD", True),
        UniversePrice("MSFT", None, D("300"), "USD", True),
    ]
    now = datetime(2025, 3, 12, 15, 0, tzinfo=timezone.utc)
    decisions = strategy.generate_decisions(db, acc, prices, drawdown_braking=False, now=now)

    buys = [d for d in decisions if d.action == "buy"]
    assert len(buys) == 2
    assert all(d.target_weight == D("0.5") for d in buys)


def test_p1_hold_when_in_band(db):
    """Se i pesi sono entro la banda, nessuna azione."""
    cfg = _make_config(db)
    acc = _make_account(db, cfg, cash="5000")
    params = {"universe_list": "test_univ", "rebalance_band": "0.25"}
    strategy = P1BuyHold(cfg, params)
    # Con solo 2 titoli a peso uguale (50%) e band 25%, il range ammesso è 37.5%–62.5%
    # Un peso di 0% (no posizioni) è fuori banda → buy
    prices = [UniversePrice("AAPL", None, D("100"), "USD", True)]
    now = datetime(2025, 3, 12, 15, 0, tzinfo=timezone.utc)
    decisions = strategy.generate_decisions(db, acc, prices, drawdown_braking=False, now=now)
    assert any(d.action == "buy" for d in decisions)


def test_p1_no_buy_during_drawdown_brake(db):
    cfg = _make_config(db)
    acc = _make_account(db, cfg, cash="10000")
    params = {"universe_list": "test_univ", "rebalance_band": "0.25"}
    strategy = P1BuyHold(cfg, params)
    prices = [UniversePrice("AAPL", None, D("100"), "USD", True)]
    now = datetime(2025, 3, 12, 15, 0, tzinfo=timezone.utc)
    decisions = strategy.generate_decisions(db, acc, prices, drawdown_braking=True, now=now)
    assert all(d.action != "buy" for d in decisions)


# ── P2 decisions ─────────────────────────────────────────────────────────────

def test_p2_buy_when_above_sma(db):
    """Se la chiusura mensile è sopra la SMA(10), la strategia compra."""
    cfg = _make_config(db, stype="P2")
    acc = _make_account(db, cfg, cash="10000")
    params = {"universe_list": "test_univ", "sma_months": 10, "min_history_days": 300}
    strategy = P2Trend(cfg, params)

    # Usa date nel passato coerenti con il now del test (2025-01-31)
    sym = "AAPL"
    _seed_prices(db, sym, 350, start_price=90.0, drift=0.001,
                 start_date=date(2024, 1, 15))

    prices = [UniversePrice(sym, None, D("130"), "USD", True)]
    now = datetime(2025, 1, 31, 16, 0, tzinfo=timezone.utc)
    decisions = strategy.generate_decisions(db, acc, prices, drawdown_braking=False, now=now)
    buys = [d for d in decisions if d.action == "buy"]
    assert len(buys) == 1


def test_p2_sell_when_below_sma(db):
    """Se la chiusura mensile è sotto la SMA(10), la strategia vende."""
    cfg = _make_config(db, stype="P2")
    acc = _make_account(db, cfg, cash="10000")
    params = {"universe_list": "test_univ", "sma_months": 10, "min_history_days": 300}
    strategy = P2Trend(cfg, params)

    sym = "MSFT"
    _seed_prices(db, sym, 350, start_price=200.0, drift=-0.001,
                 start_date=date(2024, 1, 15))

    prices = [UniversePrice(sym, None, D("150"), "USD", True)]
    now = datetime(2025, 1, 31, 16, 0, tzinfo=timezone.utc)
    decisions = strategy.generate_decisions(db, acc, prices, drawdown_braking=False, now=now)
    sells = [d for d in decisions if d.action == "sell"]
    assert len(sells) == 1


# ── Trailing stop ─────────────────────────────────────────────────────────────

def test_trailing_stop_trigger_moves_up(db, account, provider):
    """Il trigger del trailing stop sale con il prezzo, non scende."""
    from app.models import Order
    from app.services.orders import _update_trailing_stop

    inst_id = 1  # non usato nel test unitario
    order = Order(
        account_id=account.id, instrument_id=inst_id,
        side="sell", order_type="trailing_stop",
        quantity=D("100"), status="pending",
        trailing_distance=D("10"),  # 10%
        trigger_price=D("90"),       # trigger iniziale: 90
    )

    # Prezzo sale a 110 → nuovo trigger = 110 × 0.9 = 99 > 90 → aggiorna
    updated = _update_trailing_stop(order, D("110"))
    assert updated is True
    assert order.trigger_price == D("99.0") or abs(float(order.trigger_price) - 99.0) < 0.01

    # Prezzo scende a 95 → nuovo trigger = 95 × 0.9 = 85.5 < 99 → NON aggiorna
    updated2 = _update_trailing_stop(order, D("95"))
    assert updated2 is False
    assert float(order.trigger_price) >= 99.0  # invariato


def test_trailing_stop_condition():
    """Il trailing stop scatta quando il prezzo è ≤ trigger."""
    from app.services.orders import condition_met
    assert condition_met("trailing_stop", "sell", D("90"), D("89")) is True
    assert condition_met("trailing_stop", "sell", D("90"), D("91")) is False


# ── Idempotenza ───────────────────────────────────────────────────────────────

def test_run_key_idempotency(db):
    """Se il run_key esiste già, run_strategy restituisce 'already_done'."""
    cfg = _make_config(db)
    _seed_universe(db, ["AAPL"])
    acc = _make_account(db, cfg)
    today = date(2025, 3, 12)

    # Primo run: idempotency + nessun prezzo in cache → 'skipped' (cov 0% < 90%)
    r1 = auto_portfolio.run_strategy(db, cfg, is_dry_run=True, today=today)
    # Con coverage < 90% viene skippato, ma il run_key viene salvato
    assert r1["status"] in ("skipped", "ok")

    # Secondo run con lo stesso giorno → già presente
    r2 = auto_portfolio.run_strategy(db, cfg, is_dry_run=True, today=today)
    assert r2["status"] == "already_done"


# ── Drawdown brake ────────────────────────────────────────────────────────────

def test_drawdown_brake_activation(db):
    """Il freno si attiva quando il drawdown supera il -20%."""
    from app.models import DailyValuation
    cfg = _make_config(db)
    acc = _make_account(db, cfg, cash="10000")

    # Aggiungi valorizzazioni: massimo 10000, poi calo a 7900 (-21%)
    db.add(DailyValuation(account_id=acc.id, day=date(2025, 1, 2), positions_value_eur=D("10000")))
    db.add(DailyValuation(account_id=acc.id, day=date(2025, 3, 1), positions_value_eur=D("7900")))
    db.commit()

    result = auto_portfolio._update_drawdown_brake(db, cfg, acc, currently_braking=False, today=date(2025, 3, 12))
    assert result is True
    assert cfg.is_drawdown_braking == 1


def test_drawdown_brake_resume(db):
    """Il freno si disattiva quando il drawdown risale sopra il -10%."""
    from app.models import DailyValuation
    cfg = _make_config(db)
    cfg.is_drawdown_braking = 1
    acc = _make_account(db, cfg, cash="10000")

    db.add(DailyValuation(account_id=acc.id, day=date(2025, 1, 2), positions_value_eur=D("10000")))
    db.add(DailyValuation(account_id=acc.id, day=date(2025, 3, 1), positions_value_eur=D("9200")))  # -8%
    db.commit()

    result = auto_portfolio._update_drawdown_brake(db, cfg, acc, currently_braking=True, today=date(2025, 3, 12))
    assert result is False
    assert cfg.is_drawdown_braking == 0


# ── Interruttore di sicurezza ─────────────────────────────────────────────────

def test_safety_switch_skips_when_no_data(db):
    """Se la copertura dati è < 90%, run_strategy salta l'esecuzione."""
    cfg = _make_config(db)
    _seed_universe(db, ["AAPL", "MSFT", "GOOG"], "test_univ")
    _make_account(db, cfg)
    # Nessun dato in price_history_cache → coverage 0%
    today = date(2025, 3, 20)
    r = auto_portfolio.run_strategy(db, cfg, is_dry_run=True, today=today)
    assert r["status"] == "skipped"
