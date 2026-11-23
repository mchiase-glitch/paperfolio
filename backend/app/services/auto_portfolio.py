"""
Orchestratore dei portafogli automatici.

Implementa il flusso a 6 passi per ogni esecuzione:
1. Universo      – lista titoli ammessi
2. Segnale       – decisioni della strategia (buy/sell/hold/skip)
3. Filtri rischio– interruttore di sicurezza, drawdown brake
4. Sizing        – calcolo quantità ordini
5. Ordini        – piazzamento (a mercato, dry-run non piazza)
6. Registro      – StrategyDecision per ogni titolo

Chiamato dallo scheduler (EU close / US close) e dal pulsante "Prova ora".
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import (
    Account, Instrument, Order, Price,
    StrategyConfig, StrategyDecision, StrategyRun, DailyValuation,
)
from . import positions as positions_svc
from .universes import get_symbols
from .price_history import fetch_many, coverage_pct
from .strategies.base import BaseStrategy, Decision, UniversePrice
from .strategies.p1_buy_hold import P1BuyHold
from .strategies.p2_trend import P2Trend

log = logging.getLogger("paperfolio.auto")

ZERO = Decimal("0")

# Soglia di copertura dati per l'interruttore di sicurezza
SAFETY_MIN_COVERAGE = 0.75  # almeno il 75% dei simboli deve avere dati
DRAWDOWN_ACTIVATE = Decimal("-0.20")   # -20%: attiva il freno
DRAWDOWN_RESUME = Decimal("-0.10")     # -10%: riprende gli acquisti

# Mappa tipo → classe strategia
STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "P1": P1BuyHold,
    "P2": P2Trend,
}

# Quanti giorni di borsa indietro al riavvio per il recovery
RECOVERY_DAYS = 3


# ── Entry point principale ────────────────────────────────────────────────────

def run_all_strategies(db: Session, is_dry_run: bool = False, today: date | None = None) -> list[dict]:
    """
    Esegue tutte le strategie attive. Chiamato dallo scheduler.
    Restituisce un riassunto di ogni esecuzione.
    """
    if today is None:
        today = datetime.utcnow().date()

    configs = db.scalars(
        select(StrategyConfig).where(StrategyConfig.is_paused == 0)
    ).all()

    results = []
    for cfg in configs:
        try:
            result = run_strategy(db, cfg, is_dry_run=is_dry_run, today=today)
            results.append(result)
        except Exception as exc:
            log.error("Errore strategia %s (%s): %s", cfg.name, cfg.strategy_type, exc, exc_info=True)
            results.append({"config_id": cfg.id, "status": "error", "note": str(exc)})
    return results


def run_strategy(
    db: Session,
    config: StrategyConfig,
    is_dry_run: bool = False,
    today: date | None = None,
) -> dict:
    """
    Esegue un singolo ciclo di strategia. Idempotente: se il run_key esiste già, skips.
    """
    now = utcnow()
    if today is None:
        today = now.date()

    params = json.loads(config.params_json) if config.params_json else {}
    strategy_cls = STRATEGY_CLASSES.get(config.strategy_type)
    if strategy_cls is None:
        return {"config_id": config.id, "status": "skipped", "note": f"Tipo {config.strategy_type} non implementato"}

    strategy: BaseStrategy = strategy_cls(config, params)

    # ── Idempotenza ──────────────────────────────────────────────────────────
    run_key = strategy.run_key(today)
    existing = db.scalar(select(StrategyRun).where(StrategyRun.run_key == run_key))
    if existing is not None:
        return {"config_id": config.id, "run_id": existing.id, "status": "already_done", "run_key": run_key}

    # ── Account collegato ────────────────────────────────────────────────────
    account = db.scalar(select(Account).where(Account.strategy_config_id == config.id))
    if account is None:
        return {"config_id": config.id, "status": "skipped", "note": "Nessun portafoglio collegato"}

    # ── Passo 1: Universo ────────────────────────────────────────────────────
    universe_list = params.get("universe_list")
    if not universe_list:
        return {"config_id": config.id, "status": "skipped", "note": "universe_list non configurata"}

    symbols = get_symbols(db, [universe_list])
    if not symbols:
        return {"config_id": config.id, "status": "skipped", "note": f"Lista universo {universe_list!r} vuota"}

    # ── Aggiorna cache prezzi ────────────────────────────────────────────────
    if not is_dry_run:
        fetch_many(db, symbols)

    # ── Passo 3: Interruttore di sicurezza ───────────────────────────────────
    cov = coverage_pct(db, symbols, min_days=252)
    if cov < SAFETY_MIN_COVERAGE:
        run = _save_run(db, config, account, run_key, now, is_dry_run, "skipped",
                        f"Copertura dati {cov*100:.0f}% < {SAFETY_MIN_COVERAGE*100:.0f}%: esecuzione saltata")
        db.commit()
        return {"config_id": config.id, "run_id": run.id, "status": "skipped"}

    # ── Controlla se la strategia gira oggi ─────────────────────────────────
    if not strategy.should_run_today(db, today):
        run = _save_run(db, config, account, run_key, now, is_dry_run, "skipped",
                        "Non è il giorno previsto per questa strategia")
        db.commit()
        return {"config_id": config.id, "run_id": run.id, "status": "skipped"}

    # ── Passo 3b: Drawdown brake ─────────────────────────────────────────────
    drawdown_braking = bool(config.is_drawdown_braking)
    drawdown_braking = _update_drawdown_brake(db, config, account, drawdown_braking, today)

    # ── Prezzi correnti dell'universo ────────────────────────────────────────
    universe_prices = _build_universe_prices(db, symbols)

    # ── Passo 2: Segnale (delegato alla strategia) ───────────────────────────
    decisions = strategy.generate_decisions(db, account, universe_prices, drawdown_braking, now)

    # ── Passo 4+5: Sizing e ordini ───────────────────────────────────────────
    run = _save_run(db, config, account, run_key, now, is_dry_run, "ok", None)

    orders_placed = 0
    for dec in decisions:
        order_id = None
        if dec.action in ("buy", "sell") and not is_dry_run:
            order_id = _place_order(db, account, dec, universe_prices, run.id)
            if order_id:
                orders_placed += 1

        # ── Passo 6: Registro ────────────────────────────────────────────────
        db.add(StrategyDecision(
            run_id=run.id,
            symbol=dec.symbol,
            action=dec.action,
            reason_it=dec.reason_it,
            signal_data_json=dec.signal_data_json(),
            order_id=order_id,
        ))

    db.commit()
    log.info("Strategia %s (%s) ok: %d decisioni, %d ordini", config.name, config.strategy_type,
             len(decisions), orders_placed)
    return {
        "config_id": config.id,
        "run_id": run.id,
        "status": "ok",
        "decisions": len(decisions),
        "orders": orders_placed,
        "is_dry_run": is_dry_run,
    }


# ── Recovery al riavvio ───────────────────────────────────────────────────────

def recovery_run(db: Session) -> None:
    """
    Al riavvio del server: riesegue le strategie per i giorni mancanti (≤ 3 giorni di borsa).
    Usa dry_run=False solo se il run_key non esiste già.
    """
    today = datetime.utcnow().date()
    for d in _last_n_trading_days(today, RECOVERY_DAYS):
        run_all_strategies(db, is_dry_run=False, today=d)


# ── Helpers privati ───────────────────────────────────────────────────────────

def _save_run(
    db: Session, config: StrategyConfig, account: Account,
    run_key: str, ran_at: datetime, is_dry_run: bool,
    status: str, note: str | None,
) -> StrategyRun:
    run = StrategyRun(
        strategy_config_id=config.id,
        account_id=account.id,
        run_key=run_key,
        ran_at=ran_at,
        is_dry_run=1 if is_dry_run else 0,
        status=status,
        note=note,
    )
    db.add(run)
    db.flush()
    return run


def _build_universe_prices(db: Session, symbols: list[str]) -> list[UniversePrice]:
    """Costruisce la lista dei prezzi correnti per ogni simbolo dell'universo."""
    result = []
    for sym in symbols:
        instr = db.scalar(select(Instrument).where(Instrument.symbol == sym))
        instr_id = instr.id if instr else None
        price_row = db.scalar(select(Price).where(Price.instrument_id == instr_id)) if instr_id else None
        if price_row:
            result.append(UniversePrice(
                symbol=sym,
                instrument_id=instr_id,
                price=price_row.price,
                currency=price_row.currency,
                available=True,
            ))
        else:
            result.append(UniversePrice(symbol=sym, instrument_id=instr_id,
                                        price=ZERO, currency="EUR", available=False))
    return result


def _place_order(
    db: Session, account: Account, dec: Decision,
    prices: list[UniversePrice], run_id: int,
) -> int | None:
    """Piazza un ordine di mercato per la decisione. Restituisce l'id dell'ordine."""
    price_map = {up.symbol: up for up in prices}
    up = price_map.get(dec.symbol)
    if not up or not up.instrument_id or not up.available or up.price <= ZERO:
        return None

    if dec.action == "buy":
        if dec.target_weight is None:
            return None
        # Calcola il valore target
        total = positions_svc.cash_balance(db, account.id) + _portfolio_value(db, account.id, price_map)
        target_value = total * dec.target_weight
        pos = positions_svc.position(db, account.id, up.instrument_id)
        current_value = (pos.quantity * up.price) if pos.quantity > ZERO else ZERO
        buy_value = target_value - current_value
        if buy_value <= ZERO:
            return None
        qty = (buy_value / up.price).quantize(Decimal("0.0001"))
        if qty <= ZERO:
            return None
        side = "buy"
    elif dec.action == "sell":
        pos = _positions_svc.position(db, account.id, up.instrument_id)
        if pos.quantity <= ZERO:
            return None
        if dec.target_weight is not None and dec.target_weight > ZERO:
            # Vendi per raggiungere il target weight
            total = positions_svc.cash_balance(db, account.id) + _portfolio_value(db, account.id, price_map)
            target_value = total * dec.target_weight
            current_value = pos.quantity * up.price
            sell_value = current_value - target_value
            if sell_value <= ZERO:
                return None
            qty = (sell_value / up.price).quantize(Decimal("0.0001"))
            if qty > pos.quantity:
                qty = pos.quantity
        else:
            # Vendi tutto
            qty = pos.quantity
        side = "sell"
    else:
        return None

    order = Order(
        account_id=account.id,
        instrument_id=up.instrument_id,
        side=side,
        order_type="market",
        quantity=qty,
        status="pending",
        note=f"Auto [{dec.reason_it[:100]}]",
    )
    db.add(order)
    db.flush()
    return order.id


def _portfolio_value(db: Session, account_id: int, price_map: dict) -> Decimal:
    """Valore di mercato delle posizioni aperte, usando price_map {symbol: UniversePrice}."""
    all_positions = positions_svc.open_positions(db, account_id)
    total = ZERO
    for pos in all_positions.values():
        if pos.quantity <= ZERO:
            continue
        instr = db.get(Instrument, pos.instrument_id)
        if instr:
            up = price_map.get(instr.symbol)
            if up and up.available:
                total += pos.quantity * up.price
    return total


def _update_drawdown_brake(
    db: Session, config: StrategyConfig, account: Account,
    currently_braking: bool, today: date,
) -> bool:
    """
    Controlla il drawdown dal massimo storico delle valorizzazioni giornaliere.
    Attiva il freno a -20%, lo disattiva a -10%.
    """
    # Massimo storico delle valorizzazioni
    rows = db.scalars(
        select(DailyValuation)
        .where(DailyValuation.account_id == account.id)
        .order_by(DailyValuation.day)
    ).all()
    if not rows:
        return currently_braking

    max_val = max(r.positions_value_eur for r in rows)
    if max_val <= ZERO:
        return currently_braking

    last_val = rows[-1].positions_value_eur
    dd = (last_val - max_val) / max_val  # negativo

    if not currently_braking and dd <= DRAWDOWN_ACTIVATE:
        log.warning("Strategia %s: drawdown brake ATTIVATO (dd=%.1f%%)", config.name, float(dd) * 100)
        config.is_drawdown_braking = 1
        db.flush()
        return True
    elif currently_braking and dd >= DRAWDOWN_RESUME:
        log.info("Strategia %s: drawdown brake DISATTIVATO (dd=%.1f%%)", config.name, float(dd) * 100)
        config.is_drawdown_braking = 0
        db.flush()
        return False
    return currently_braking


def _last_n_trading_days(end: date, n: int) -> list[date]:
    """Restituisce gli ultimi n giorni lavorativi (lun-ven) fino a end incluso."""
    result = []
    d = end
    while len(result) < n:
        if d.weekday() < 5:  # lun-ven
            result.append(d)
        d -= timedelta(days=1)
    return list(reversed(result))
