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
from dataclasses import dataclass
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
from sqlalchemy import func

from . import instruments as instruments_svc
from . import orders as orders_svc
from . import positions as positions_svc
from . import prices as prices_svc
from .auto_rules import (  # noqa: F401
    BRAKE_WINDOW_DAYS, CASH_BUFFER, DRAWDOWN_ACTIVATE, DRAWDOWN_RESUME, brake_state, drawdown, order_quantity,
)
from .price_history import FETCH_DELAY_S, fetch_history, fetch_many, get_rows, has_enough_history
from .strategies import STRATEGY_CLASSES
from .strategies.base import BaseStrategy, Decision, StrategyContext, UniversePrice
from .universes import get_items, get_symbols

log = logging.getLogger("paperfolio.auto")

ROME = ZoneInfo(app_config.DISPLAY_TZ)
ZERO = Decimal("0")

# Soglia di copertura dati per l'interruttore di sicurezza
SAFETY_MIN_COVERAGE = 0.75  # almeno il 75% dei simboli deve avere dati
MIN_HISTORY_DAYS = 252


class LiveContext(StrategyContext):
    """Il portafoglio vero: posizioni dal ledger, storico dalla cache."""

    def __init__(self, db: Session, account: Account, today: date):
        self.db, self.account, self.today = db, account, today
        self._ids: dict[str, int | None] = {}

    def _instrument_id(self, symbol: str) -> int | None:
        if symbol not in self._ids:
            self._ids[symbol] = self.db.scalar(select(Instrument.id).where(Instrument.symbol == symbol))
        return self._ids[symbol]

    def quantity(self, symbol: str) -> Decimal:
        iid = self._instrument_id(symbol)
        return positions_svc.position(self.db, self.account.id, iid).quantity if iid else ZERO

    def cash(self) -> Decimal:
        return positions_svc.cash_balance(self.db, self.account.id)

    def history(self, symbol: str, start: date, end: date) -> list:
        return get_rows(self.db, symbol, start, min(end, self.today))

    def history_count(self, symbol: str) -> int:
        from ..models import PriceHistoryCache
        return self.db.scalar(select(func.count(PriceHistoryCache.id)).where(
            PriceHistoryCache.symbol == symbol, PriceHistoryCache.date <= self.today)) or 0

    def closes(self, symbol: str) -> tuple[list[date], list[float], int]:
        if not hasattr(self, "_closes"):
            self._closes: dict[str, tuple[list[date], list[float], int]] = {}
        if symbol not in self._closes:
            rows = get_rows(self.db, symbol, self.today - timedelta(days=CLOSES_WINDOW_DAYS), self.today)
            self._closes[symbol] = ([r.date for r in rows], [r.close for r in rows], len(rows) - 1)
        return self._closes[symbol]

    def entry_date(self, symbol: str) -> date | None:
        """Giorno dell'acquisto che ha aperto la posizione attuale (quantità passata da zero a positiva)."""
        iid = self._instrument_id(symbol)
        if not iid:
            return None
        qty, opened = ZERO, None
        for e in positions_svc.ledger(self.db, self.account.id):
            if e.instrument_id != iid or e.kind not in ("buy", "sell", "redemption", "split"):
                continue
            if e.kind == "buy":
                if qty <= 0:
                    opened = e.ts.astimezone(ROME).date()
                qty += e.quantity
            elif e.kind == "split":
                qty *= e.ratio
            else:
                qty -= e.quantity
        return opened if qty > 0 else None


# Storico letto dal vivo per gli indicatori: momentum 12-1 e media a 200 giorni più un margine
CLOSES_WINDOW_DAYS = 450


@dataclass
class StrategySymbols:
    tradeable: list[str]          # titoli e ETF che la strategia può comprare
    reference: list[str]          # indici e cambi letti dai segnali
    groups: dict[str, tuple[str, ...]]  # simbolo → liste di universo che lo contengono
    key: str                      # identifica la preparazione dei dati (condivisa tra strategie uguali)


def strategy_symbols(db: Session, strategy: BaseStrategy) -> StrategySymbols:
    lists = strategy.universe_lists()
    groups: dict[str, tuple[str, ...]] = {}
    for name in lists:
        for sym in get_symbols(db, [name]):
            groups[sym] = groups.get(sym, ()) + (name,)
    extra = [s for s in strategy.extra_tradeable() if s not in groups]
    tradeable = list(groups) + extra
    reference = strategy.reference_symbols()
    key = "+".join(sorted(lists)) + ("|" + ",".join(sorted(extra + reference)) if extra or reference else "")
    return StrategySymbols(tradeable, reference, groups, key)


def make_strategy(config: StrategyConfig) -> BaseStrategy | None:
    cls = STRATEGY_CLASSES.get(config.strategy_type)
    params = json.loads(config.params_json) if config.params_json else {}
    return cls(config, params) if cls else None


def strategy_region(strategy: BaseStrategy) -> str:
    """Sessione in cui gira la strategia: solo titoli USA → sera (21:30); altrimenti pomeriggio (17:00),
    quando sono aperte sia le borse europee sia Wall Street."""
    lists = strategy.universe_lists()
    return "US" if lists and all(name == "sp100" for name in lists) and not strategy.extra_tradeable() else "EU"


# ── Entry point principale ────────────────────────────────────────────────────

def run_all_strategies(db: Session, is_dry_run: bool = False, today: date | None = None,
                       region: str | None = None) -> list[dict]:
    """Esegue tutte le strategie attive (eventualmente solo quelle di un mercato). Chiamato dallo scheduler."""
    configs = db.scalars(
        select(StrategyConfig).where(StrategyConfig.is_paused == 0).order_by(StrategyConfig.id)
    ).all()

    results = []
    for cfg in configs:
        strategy = make_strategy(cfg)
        if region and (strategy is None or strategy_region(strategy) != region):
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

    strategy = make_strategy(config)
    if strategy is None:
        return {"config_id": config.id, "status": "skipped", "note": f"Tipo {config.strategy_type} non implementato"}

    # ── Idempotenza (solo esecuzioni reali) ──────────────────────────────────
    run_key = strategy.run_key(today)
    if not is_dry_run:
        existing = db.scalar(select(StrategyRun).where(StrategyRun.run_key == run_key))
        if existing is not None:
            return {"config_id": config.id, "run_id": existing.id, "status": "already_done", "run_key": run_key}
        if not strategy.should_run_today(today):
            return {"config_id": config.id, "status": "not_today"}

    # ── Account collegato ────────────────────────────────────────────────────
    account = db.scalar(select(Account).where(Account.strategy_config_id == config.id))
    if account is None:
        return {"config_id": config.id, "status": "skipped", "note": "Nessun portafoglio collegato"}

    # ── Passo 1: Universo ────────────────────────────────────────────────────
    ss = strategy_symbols(db, strategy)
    symbols = ss.tradeable
    if not symbols:
        return {"config_id": config.id, "status": "skipped", "note": "Nessun titolo nell'universo della strategia"}

    # ── Aggiorna cache prezzi (solo nello scheduler: nel dry-run la richiesta resterebbe appesa) ──
    if not is_dry_run and ready_pct(db, symbols, ss.reference) >= SAFETY_MIN_COVERAGE:
        fetch_many(db, symbols + ss.reference)

    # ── Passo 3: Interruttore di sicurezza ───────────────────────────────────
    cov = ready_pct(db, symbols, ss.reference)
    if cov < SAFETY_MIN_COVERAGE:
        start_preparation(ss)
        note = (f"Dati storici pronti per il {cov*100:.0f}% dei titoli (minimo {SAFETY_MIN_COVERAGE*100:.0f}%): "
                f"esecuzione saltata. {_preparation_text(ss.key)}")
        run = _save_run(db, config, account, _side_key(run_key, now, "skip"), now, is_dry_run, "skipped", note)
        db.commit()
        return {"config_id": config.id, "run_id": run.id, "status": "skipped", "note": note}

    note = None
    if is_dry_run and not strategy.should_run_today(today):
        note = ("Simulazione: nell'esecuzione reale questa strategia opera solo "
                + ("l'ultimo giorno di borsa del mese." if strategy.frequency == "monthly"
                   else "una volta l'anno." if strategy.frequency == "annual" else "nei giorni di borsa."))

    # ── Prezzi correnti dell'universo (in EUR) ───────────────────────────────
    universe_prices = _build_universe_prices(db, symbols, today, ss.groups)
    price_map = {up.symbol: up for up in universe_prices}
    total = positions_svc.cash_balance(db, account.id) + _portfolio_value(db, account.id, price_map)

    # ── Passo 3b: Drawdown brake (sul valore attuale, non sulla valorizzazione salvata) ──
    drawdown_braking = _update_drawdown_brake(
        db, config, account, bool(config.is_drawdown_braking), today, current=total)

    # ── Passo 2: Segnale (delegato alla strategia) ───────────────────────────
    decisions = strategy.generate_decisions(LiveContext(db, account, today), universe_prices, drawdown_braking)

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


def preparation_status(key: str) -> dict | None:
    st = _prep_state.get(key)
    return dict(st, failed=list(st["failed"])) if st else None


def start_preparation(ss: StrategySymbols) -> bool:
    """Registra i titoli della strategia e ne scarica lo storico (con indici e cambi) in un thread separato.
    False se già in corso."""
    with _prep_lock:
        st = _prep_state.get(ss.key)
        if st and st["running"]:
            return False
        _prep_state[ss.key] = {"running": True, "done": 0, "total": len(ss.tradeable) + len(ss.reference),
                               "failed": []}
    threading.Thread(target=_prepare, args=(ss,), daemon=True, name=f"prep-{ss.key[:20]}").start()
    return True


def _prepare(ss: StrategySymbols) -> None:
    from ..database import SessionLocal
    from ..models import UniverseListItem
    st = _prep_state[ss.key]
    try:
        with SessionLocal() as db:
            isins = {i.symbol: i.isin for i in db.scalars(select(UniverseListItem).where(
                UniverseListItem.symbol.in_(ss.tradeable)))}
            for sym in ss.tradeable + ss.reference:
                try:
                    if sym in ss.tradeable:
                        instruments_svc.get_or_create(db, sym, isins.get(sym))
                    fetch_history(db, sym)
                except Exception as exc:
                    db.rollback()
                    st["failed"].append(sym)
                    log.warning("Preparazione %s: %s non disponibile (%s)", ss.key, sym, exc)
                st["done"] += 1
                time.sleep(FETCH_DELAY_S)
    except Exception:
        log.exception("Preparazione dati %s interrotta", ss.key)
    finally:
        st["running"] = False


def ready_pct(db: Session, symbols: list[str], reference: list[str] | None = None) -> float:
    """Quota di dati pronti: titoli registrati come strumento e con storico sufficiente,
    indici e cambi con storico sufficiente."""
    reference = reference or []
    if not symbols and not reference:
        return 1.0
    known = set(db.scalars(select(Instrument.symbol).where(Instrument.symbol.in_(symbols))))
    ok = sum(1 for s in symbols if s in known and has_enough_history(db, s, MIN_HISTORY_DAYS))
    ok += sum(1 for s in reference if has_enough_history(db, s, MIN_HISTORY_DAYS))
    return ok / (len(symbols) + len(reference))


def _preparation_text(key: str) -> str:
    st = preparation_status(key)
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


def _build_universe_prices(db: Session, symbols: list[str], today: date,
                           groups: dict[str, tuple[str, ...]] | None = None) -> list[UniversePrice]:
    """
    Ultima chiusura in cache di ogni titolo, convertita in EUR.
    Un titolo non registrato come strumento o senza prezzi recenti non è negoziabile.
    """
    groups = groups or {}
    fx_cache: dict[str, Decimal | None] = {}
    result = []
    for sym in symbols:
        instr = db.scalar(select(Instrument).where(Instrument.symbol == sym))
        rows = get_rows(db, sym, today - timedelta(days=14), today)
        meta = dict(groups=groups.get(sym, ()))
        if instr is not None:
            meta.update(market=instr.market, instrument_type=instr.type, listing_currency=instr.currency)
        if instr is None or not rows:
            result.append(UniversePrice(sym, instr.id if instr else None, ZERO, "EUR", False, **meta))
            continue
        if instr.currency not in fx_cache:
            try:
                fx_cache[instr.currency] = prices_svc.get_fx(db, instr.currency)[0]
            except DataProviderError:
                fx_cache[instr.currency] = None
        fx = fx_cache[instr.currency]
        if not fx:
            result.append(UniversePrice(sym, instr.id, ZERO, "EUR", False, **meta))
            continue
        result.append(UniversePrice(sym, instr.id, Decimal(str(rows[-1].close)) / fx, "EUR", True, **meta))
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
    free = held - positions_svc.pending_sell_quantity(db, account.id, inst.id)
    qty, err = order_quantity(dec.action, dec.target_weight, held, free, up.price, total)
    if err:
        return None, err
    try:
        if dec.action == "buy":
            # Riduce la quantità se la liquidità libera non basta (prenotazione a mercato chiuso, commissioni)
            pv = orders_svc.preview(db, account, inst, "buy", qty, now)
            needed = pv.net_eur if pv.executes_now else pv.reserved_eur
            available = positions_svc.cash_balance(db, account.id) - positions_svc.reserved_cash(db, account.id)
            if needed > available:
                qty = _floor(qty * available / needed)
                if qty <= 0:
                    return None, "liquidità insufficiente"
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
    since = today - timedelta(days=BRAKE_WINDOW_DAYS) if today is not None else None
    entries = db.scalars(
        select(LedgerEntry).where(LedgerEntry.account_id == account.id).order_by(LedgerEntry.ts, LedgerEntry.id)
    ).all()
    series, cash, i = [], ZERO, 0
    for r in rows:
        while i < len(entries) and entries[i].ts.astimezone(ROME).date() <= r.day:
            cash += entries[i].cash_delta_eur
            i += 1
        if since is None or r.day > since:
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
    braking = brake_state(series, currently_braking)
    if braking != currently_braking:
        dd = float(drawdown(series) or 0) * 100
        log.warning("Strategia %s: freno drawdown %s (dd=%.1f%%)", config.name,
                    "ATTIVATO" if braking else "DISATTIVATO", dd)
        config.is_drawdown_braking = 1 if braking else 0
        db.flush()
    return braking
