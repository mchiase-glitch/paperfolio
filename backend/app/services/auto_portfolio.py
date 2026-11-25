"""
Orchestratore dei portafogli automatici.

Implementa il flusso a 6 passi per ogni esecuzione:
1. Universo      – lista titoli ammessi
2. Segnale       – decisioni della strategia (buy/sell/hold/skip)
3. Filtri rischio– interruttore di sicurezza, drawdown brake
4. Sizing        – calcolo quantità ordini (in EUR, azioni intere)
5. Ordini        – piazzati con il motore ordini dell'app (dry-run non piazza)
6. Registro      – StrategyDecision per ogni titolo

Chiamato dallo scheduler (mercati EU e USA ancora aperti) e dal pulsante "Prova ora" (dry-run).
Solo un'esecuzione reale riuscita "consuma" il giorno (o il mese) della strategia:
simulazioni ed esecuzioni saltate restano nel registro ma non bloccano quelle successive.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..data_provider import DataProviderError
from ..database import utcnow
from ..models import (
    Account, DailyValuation, Instrument, LedgerEntry, Order,
    StrategyConfig, StrategyDecision, StrategyRun,
)
from . import instruments as instruments_svc
from . import orders as orders_svc
from . import positions as positions_svc
from . import prices as prices_svc
from .price_history import FETCH_DELAY_S, fetch_history, fetch_many, get_rows, has_enough_history
from .strategies.base import BaseStrategy, Decision, UniversePrice
from .strategies.p1_buy_hold import P1BuyHold
from .strategies.p2_trend import P2Trend
from .universes import get_items, get_symbols

log = logging.getLogger("paperfolio.auto")

ROME = ZoneInfo(app_config.DISPLAY_TZ)
ZERO = Decimal("0")

# Soglia di copertura dati per l'interruttore di sicurezza
SAFETY_MIN_COVERAGE = 0.75  # almeno il 75% dei simboli deve avere dati
MIN_HISTORY_DAYS = 252
DRAWDOWN_ACTIVATE = Decimal("-0.20")   # -20%: attiva il freno
DRAWDOWN_RESUME = Decimal("-0.10")     # -10%: riprende gli acquisti
# Quota del capitale investita: il resto copre commissioni e piccoli scarti di prezzo
CASH_BUFFER = Decimal("0.98")

# Mappa tipo → classe strategia
STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "P1": P1BuyHold,
    "P2": P2Trend,
}

# Mercato di riferimento di ogni universo: decide in quale sessione gira la strategia
REGION_BY_UNIVERSE = {"sp100": "US"}


def universe_region(universe_list: str | None) -> str:
    return REGION_BY_UNIVERSE.get(universe_list or "", "EU")


# ── Entry point principale ────────────────────────────────────────────────────

def run_all_strategies(db: Session, is_dry_run: bool = False, today: date | None = None,
                       region: str | None = None) -> list[dict]:
    """Esegue tutte le strategie attive (eventualmente solo quelle di un mercato). Chiamato dallo scheduler."""
    configs = db.scalars(
        select(StrategyConfig).where(StrategyConfig.is_paused == 0).order_by(StrategyConfig.id)
    ).all()

    results = []
    for cfg in configs:
        params = json.loads(cfg.params_json) if cfg.params_json else {}
        if region and universe_region(params.get("universe_list")) != region:
            continue
        try:
            results.append(run_strategy(db, cfg, is_dry_run=is_dry_run, today=today))
        except Exception as exc:
            db.rollback()
            log.error("Errore strategia %s (%s): %s", cfg.name, cfg.strategy_type, exc, exc_info=True)
            results.append({"config_id": cfg.id, "status": "error", "note": str(exc)})
    return results


def run_strategy(
    db: Session,
    config: StrategyConfig,
    is_dry_run: bool = False,
    today: date | None = None,
    now: datetime | None = None,
) -> dict:
    """Esegue un singolo ciclo di strategia. Un'esecuzione reale già riuscita nello stesso periodo non si ripete."""
    now = now or utcnow()
    if today is None:
        today = now.astimezone(ROME).date()

    params = json.loads(config.params_json) if config.params_json else {}
    strategy_cls = STRATEGY_CLASSES.get(config.strategy_type)
    if strategy_cls is None:
        return {"config_id": config.id, "status": "skipped", "note": f"Tipo {config.strategy_type} non implementato"}

    strategy: BaseStrategy = strategy_cls(config, params)

    # ── Idempotenza (solo esecuzioni reali) ──────────────────────────────────
    run_key = strategy.run_key(today)
    if not is_dry_run:
        existing = db.scalar(select(StrategyRun).where(StrategyRun.run_key == run_key))
        if existing is not None:
            return {"config_id": config.id, "run_id": existing.id, "status": "already_done", "run_key": run_key}
        if not strategy.should_run_today(db, today):
            return {"config_id": config.id, "status": "not_today"}

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

    # ── Aggiorna cache prezzi (solo nello scheduler: nel dry-run la richiesta resterebbe appesa) ──
    if not is_dry_run and ready_pct(db, symbols) >= SAFETY_MIN_COVERAGE:
        fetch_many(db, symbols)

    # ── Passo 3: Interruttore di sicurezza ───────────────────────────────────
    cov = ready_pct(db, symbols)
    if cov < SAFETY_MIN_COVERAGE:
        start_preparation(universe_list)
        note = (f"Dati storici pronti per il {cov*100:.0f}% dei titoli (minimo {SAFETY_MIN_COVERAGE*100:.0f}%): "
                f"esecuzione saltata. {_preparation_text(universe_list)}")
        run = _save_run(db, config, account, _side_key(run_key, now, "skip"), now, is_dry_run, "skipped", note)
        db.commit()
        return {"config_id": config.id, "run_id": run.id, "status": "skipped", "note": note}

    note = None
    if is_dry_run and not strategy.should_run_today(db, today):
        note = "Simulazione: nell'esecuzione reale questa strategia opera solo l'ultimo giorno di borsa del mese."

    # ── Prezzi correnti dell'universo (in EUR) ───────────────────────────────
    universe_prices = _build_universe_prices(db, symbols, today)
    price_map = {up.symbol: up for up in universe_prices}
    total = positions_svc.cash_balance(db, account.id) + _portfolio_value(db, account.id, price_map)

    # ── Passo 3b: Drawdown brake (sul valore attuale, non sulla valorizzazione salvata) ──
    drawdown_braking = _update_drawdown_brake(
        db, config, account, bool(config.is_drawdown_braking), today, current=total)

    # ── Passo 2: Segnale (delegato alla strategia) ───────────────────────────
    decisions = strategy.generate_decisions(db, account, universe_prices, drawdown_braking, now)

    key = _side_key(run_key, now, "dry") if is_dry_run else run_key
    run = _save_run(db, config, account, key, now, is_dry_run, "ok", note)
    db.commit()

    # ── Passo 4+5: Sizing e ordini (prima le vendite, che liberano liquidità) ──
    outcomes: dict[str, tuple[int | None, str | None]] = {}
    if not is_dry_run:
        for side in ("sell", "buy"):
            for dec in decisions:
                if dec.action == side and dec.symbol in price_map:
                    outcomes[dec.symbol] = _place_order(db, account, config, dec, price_map[dec.symbol], total, now)

    # ── Passo 6: Registro ────────────────────────────────────────────────────
    orders_placed = 0
    for dec in decisions:
        order_id, error = outcomes.get(dec.symbol, (None, None))
        reason = dec.reason_it
        if error:
            reason = f"{reason} — ordine non piazzato: {error}"
        if order_id:
            orders_placed += 1
        db.add(StrategyDecision(
            run_id=run.id,
            symbol=dec.symbol,
            action=dec.action,
            reason_it=reason,
            signal_data_json=dec.signal_data_json(),
            order_id=order_id,
        ))
    db.commit()

    # Valorizzazione aggiornata dopo gli acquisti/vendite (grafico del valore e freno drawdown)
    if orders_placed:
        from . import portfolio as portfolio_svc
        try:
            portfolio_svc.snapshot(db, account, now)
        except Exception:  # noqa: BLE001 - la valorizzazione serale la riscrive comunque
            db.rollback()
            log.exception("Valorizzazione dopo esecuzione fallita per %s", config.name)

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

# Orari (Roma) delle esecuzioni programmate, usati anche dal recovery
SCHEDULE = {"EU": (17, 0), "US": (21, 30)}


def recovery_run(db: Session, now: datetime | None = None) -> None:
    """
    Al riavvio del server: se oggi l'esecuzione programmata è già passata ma non è avvenuta
    (server spento), la si recupera. Solo il giorno corrente: ordini con prezzi vecchi non hanno senso.
    """
    now_rome = (now or utcnow()).astimezone(ROME)
    if now_rome.weekday() >= 5:
        return
    for region, (hour, minute) in SCHEDULE.items():
        if (now_rome.hour, now_rome.minute) >= (hour, minute):
            run_all_strategies(db, today=now_rome.date(), region=region)


# ── Preparazione dati in background ──────────────────────────────────────────

_prep_lock = threading.Lock()
_prep_state: dict[str, dict] = {}


def preparation_status(universe_list: str) -> dict | None:
    st = _prep_state.get(universe_list)
    return dict(st, failed=list(st["failed"])) if st else None


def start_preparation(universe_list: str) -> bool:
    """Registra i titoli dell'universo e ne scarica lo storico in un thread separato. False se già in corso."""
    with _prep_lock:
        st = _prep_state.get(universe_list)
        if st and st["running"]:
            return False
        _prep_state[universe_list] = {"running": True, "done": 0, "total": 0, "failed": []}
    threading.Thread(target=_prepare, args=(universe_list,), daemon=True, name=f"prep-{universe_list}").start()
    return True


def _prepare(universe_list: str) -> None:
    from ..database import SessionLocal
    st = _prep_state[universe_list]
    try:
        with SessionLocal() as db:
            items = get_items(db, universe_list)
            st["total"] = len(items)
            for item in items:
                try:
                    instruments_svc.get_or_create(db, item.symbol, item.isin)
                    fetch_history(db, item.symbol)
                except Exception as exc:
                    db.rollback()
                    st["failed"].append(item.symbol)
                    log.warning("Preparazione %s: %s non disponibile (%s)", universe_list, item.symbol, exc)
                st["done"] += 1
                time.sleep(FETCH_DELAY_S)
    except Exception:
        log.exception("Preparazione universo %s interrotta", universe_list)
    finally:
        st["running"] = False


def ready_pct(db: Session, symbols: list[str]) -> float:
    """Quota di titoli negoziabili: registrati come strumento e con storico sufficiente."""
    if not symbols:
        return 1.0
    known = set(db.scalars(select(Instrument.symbol).where(Instrument.symbol.in_(symbols))))
    ok = sum(1 for s in symbols if s in known and has_enough_history(db, s, MIN_HISTORY_DAYS))
    return ok / len(symbols)


def _preparation_text(universe_list: str) -> str:
    st = preparation_status(universe_list)
    if st is None:
        return ""
    if st["running"]:
        return f"Download dei dati in corso ({st['done']}/{st['total']} titoli): riprova tra qualche minuto."
    if st["failed"]:
        return f"Titoli senza dati sulla fonte: {', '.join(st['failed'][:10])}."
    return ""


# ── Helpers privati ───────────────────────────────────────────────────────────

def _side_key(run_key: str, now: datetime, kind: str) -> str:
    """Chiave univoca per simulazioni ed esecuzioni saltate: non occupano quella del periodo."""
    return f"{run_key}#{kind}-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"


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


def _build_universe_prices(db: Session, symbols: list[str], today: date) -> list[UniversePrice]:
    """
    Ultima chiusura in cache di ogni titolo, convertita in EUR.
    Un titolo non registrato come strumento o senza prezzi recenti non è negoziabile.
    """
    fx_cache: dict[str, Decimal | None] = {}
    result = []
    for sym in symbols:
        instr = db.scalar(select(Instrument).where(Instrument.symbol == sym))
        rows = get_rows(db, sym, today - timedelta(days=14), today)
        if instr is None or not rows:
            result.append(UniversePrice(sym, instr.id if instr else None, ZERO, "EUR", False))
            continue
        if instr.currency not in fx_cache:
            try:
                fx_cache[instr.currency] = prices_svc.get_fx(db, instr.currency)[0]
            except DataProviderError:
                fx_cache[instr.currency] = None
        fx = fx_cache[instr.currency]
        if not fx:
            result.append(UniversePrice(sym, instr.id, ZERO, "EUR", False))
            continue
        result.append(UniversePrice(sym, instr.id, Decimal(str(rows[-1].close)) / fx, "EUR", True))
    return result


def _place_order(
    db: Session, account: Account, config: StrategyConfig, dec: Decision,
    up: UniversePrice, total: Decimal, now: datetime,
) -> tuple[int | None, str | None]:
    """Piazza un ordine a mercato (azioni intere) con il motore ordini. Restituisce (id ordine, errore)."""
    if not up.available or not up.instrument_id or up.price <= ZERO:
        return None, "prezzo non disponibile"
    inst = db.get(Instrument, up.instrument_id)
    pending = db.scalar(select(Order).where(Order.account_id == account.id, Order.instrument_id == inst.id,
                                            Order.status == "pending"))
    if pending is not None:
        return None, "c'è già un ordine in attesa su questo titolo"

    held = positions_svc.position(db, account.id, inst.id).quantity
    current_value = held * up.price
    target_weight = dec.target_weight or ZERO
    try:
        if dec.action == "buy":
            target_value = total * target_weight * CASH_BUFFER
            qty = _floor((target_value - current_value) / up.price)
            if qty <= 0:
                return None, "importo inferiore al prezzo di un'azione"
            # Riduce la quantità se la liquidità libera non basta (prenotazione a mercato chiuso, commissioni)
            pv = orders_svc.preview(db, account, inst, "buy", qty, now)
            needed = pv.net_eur if pv.executes_now else pv.reserved_eur
            available = positions_svc.cash_balance(db, account.id) - positions_svc.reserved_cash(db, account.id)
            if needed > available:
                qty = _floor(qty * available / needed)
                if qty <= 0:
                    return None, "liquidità insufficiente"
        else:
            free = held - positions_svc.pending_sell_quantity(db, account.id, inst.id)
            if target_weight > ZERO:
                qty = min(_floor((current_value - total * target_weight) / up.price), free)
            else:
                qty = free
            if qty <= 0:
                return None, "nessuna azione da vendere"
        order = orders_svc.place_order(db, account, inst, dec.action, qty, now)
    except (orders_svc.OrderError, DataProviderError) as exc:
        db.rollback()
        return None, str(exc)
    order.note = f"Automatico: {config.name}"
    db.commit()
    return order.id, None


def _floor(v: Decimal) -> Decimal:
    return v.to_integral_value(rounding=ROUND_FLOOR)


def _portfolio_value(db: Session, account_id: int, price_map: dict) -> Decimal:
    """Valore in EUR delle posizioni aperte, usando price_map {symbol: UniversePrice}."""
    total = ZERO
    for pos in positions_svc.open_positions(db, account_id).values():
        if pos.quantity <= ZERO:
            continue
        instr = db.get(Instrument, pos.instrument_id)
        up = price_map.get(instr.symbol) if instr else None
        if up and up.available:
            total += pos.quantity * up.price
    return total


def _equity_series(
    db: Session, account: Account, today: date | None = None, current: Decimal | None = None,
) -> list[Decimal]:
    """Valore complessivo (posizioni + liquidità) a fine giornata per ogni valorizzazione salvata.

    Con `current` il valore di oggi è quello attuale, non la valorizzazione salvata: quella può
    essere stata scritta prima degli acquisti di oggi (posizioni a zero, liquidità già spesa).
    """
    q = select(DailyValuation).where(DailyValuation.account_id == account.id)
    if current is not None and today is not None:
        q = q.where(DailyValuation.day < today)
    rows = db.scalars(q.order_by(DailyValuation.day)).all()
    entries = db.scalars(
        select(LedgerEntry).where(LedgerEntry.account_id == account.id).order_by(LedgerEntry.ts, LedgerEntry.id)
    ).all()
    series, cash, i = [], ZERO, 0
    for r in rows:
        while i < len(entries) and entries[i].ts.astimezone(ROME).date() <= r.day:
            cash += entries[i].cash_delta_eur
            i += 1
        series.append(r.positions_value_eur + cash)
    if current is not None:
        series.append(current)
    return series


def _update_drawdown_brake(
    db: Session, config: StrategyConfig, account: Account,
    currently_braking: bool, today: date, current: Decimal | None = None,
) -> bool:
    """
    Drawdown del valore complessivo dal massimo storico.
    Attiva il freno a -20%, lo disattiva a -10%.
    """
    series = _equity_series(db, account, today, current)
    if not series:
        return currently_braking
    max_val = max(series)
    if max_val <= ZERO:
        return currently_braking
    dd = (series[-1] - max_val) / max_val  # negativo

    if not currently_braking and dd <= DRAWDOWN_ACTIVATE:
        log.warning("Strategia %s: drawdown brake ATTIVATO (dd=%.1f%%)", config.name, float(dd) * 100)
        config.is_drawdown_braking = 1
        db.flush()
        return True
    if currently_braking and dd >= DRAWDOWN_RESUME:
        log.info("Strategia %s: drawdown brake DISATTIVATO (dd=%.1f%%)", config.name, float(dd) * 100)
        config.is_drawdown_braking = 0
        db.flush()
        return False
    return currently_braking
