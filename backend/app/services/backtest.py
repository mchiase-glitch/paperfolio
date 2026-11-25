"""
Motore di backtest dei portafogli automatici.

Simula una strategia sul passato con le stesse regole del portafoglio vero:
- stessa strategia (stesso codice) e stesso dimensionamento (`auto_rules`);
- segnale alla chiusura, esecuzione al prezzo di apertura del giorno di borsa successivo;
- commissioni, Tobin tax, spread di cambio, imposta sulle plusvalenze con zainetto e scadenze,
  dividendi con ritenuta estera e imposta italiana, bollo pro rata calcolato giorno per giorno;
- split: i prezzi della fonte sono già rettificati, quantità e dividendi sono nella stessa unità.

Lo stato simulato vive solo in memoria e i risultati vanno nelle tabelle backtest_*: il ledger
dei portafogli veri non viene mai toccato.
"""
from __future__ import annotations

import json
import logging
import threading
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import (
    BacktestRun, BacktestTrade, CommissionRule, Instrument, PriceHistoryCache, TaxRule, WithholdingRate,
)
from . import metrics, settings
from .auto_rules import BRAKE_WINDOW_DAYS, brake_state, floor_qty, order_quantity
from .commission import commission, tobin_tax
from .corporate_events import dividend_breakdown
from .fx import to_eur
from .money import ZERO, eur
from .price_history import DayRow, fetch_history
from .strategies import STRATEGY_CLASSES, STRATEGY_VERSIONS
from .strategies.base import BaseStrategy, StrategyContext, UniversePrice
from .tax import LossLot, compute_sale_tax, days_in_year

log = logging.getLogger("paperfolio.backtest")

DEFAULT_START = date(2010, 1, 1)
LOOKBACK_DAYS = 500          # storico caricato prima dell'inizio, per medie e momentum
STALE_DAYS = 14              # oltre questo distacco l'ultimo prezzo non vale più
PENDING_MAX_DAYS = 5         # giorni di borsa in cui un ordine aspetta un prezzo di apertura
OVERFITTING_WARNING = 10     # oltre questo numero di backtest si avvisa del rischio di adattamento al passato

# Indice di confronto per ogni universo: (simbolo Yahoo, nome, valuta)
BENCHMARKS = {
    "ftse_mib": ("FTSEMIB.MI", "FTSE MIB", "EUR"),
    "eurostoxx50": ("^STOXX50E", "Euro Stoxx 50", "EUR"),
    "sp100": ("^OEX", "S&P 100", "USD"),
}


def fx_symbol(currency: str) -> str:
    """Cambio Yahoo: unità di valuta per 1 EUR (es. EURUSD=X ≈ 1,08)."""
    return f"EUR{currency}=X"


# ── Dati in ingresso ──────────────────────────────────────────────────────────

@dataclass
class InstrumentInfo:
    symbol: str
    type: str
    market: str
    country: str | None
    currency: str
    fiscal_category: str


@dataclass
class CommRule:
    fixed: Decimal
    pct: Decimal
    minimum: Decimal


@dataclass
class TaxInfo:
    """Stessi campi di TaxRule usati da compute_sale_tax."""
    rate: Decimal
    base_factor: Decimal
    gains_kind: str
    losses_kind: str


@dataclass
class Costs:
    commissions: dict[tuple[str, str], CommRule]
    tax_rules: dict[str, TaxInfo]
    withholding: dict[str, Decimal]
    tobin_rate: Decimal
    fx_spread: Decimal
    stamp_rate: Decimal


class Series:
    """Storico giornaliero di un simbolo, in ordine di data, con ricerca binaria."""

    def __init__(self, rows: list[DayRow]):
        self.rows = rows
        self.dates = [r.date for r in rows]

    def idx_le(self, d: date) -> int:
        return bisect_right(self.dates, d) - 1

    def row_on(self, d: date) -> DayRow | None:
        i = self.idx_le(d)
        return self.rows[i] if i >= 0 and self.dates[i] == d else None

    def close_le(self, d: date, max_age: int | None = None) -> float | None:
        i = self.idx_le(d)
        if i < 0 or (max_age is not None and (d - self.dates[i]).days > max_age):
            return None
        return self.rows[i].close


# ── Stato simulato ────────────────────────────────────────────────────────────

@dataclass
class Holding:
    qty: Decimal = ZERO
    cost_gross: Decimal = ZERO   # solo prezzo, in EUR
    cost_fiscal: Decimal = ZERO  # prezzo + commissioni di acquisto


@dataclass
class PendingOrder:
    symbol: str
    side: str
    qty: Decimal
    reason: str
    created: date
    waited: int = 0


@dataclass
class TradeRec:
    day: date
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    currency: str
    gross_eur: Decimal
    costs_eur: Decimal
    tax_eur: Decimal
    cash_delta_eur: Decimal
    realized_eur: Decimal | None
    reason: str


@dataclass
class Totals:
    commissions: Decimal = ZERO
    tobin: Decimal = ZERO
    capital_gain_tax: Decimal = ZERO
    dividends_gross: Decimal = ZERO
    withholding: Decimal = ZERO
    dividend_tax: Decimal = ZERO
    stamp: Decimal = ZERO
    bought_eur: Decimal = ZERO
    sold_eur: Decimal = ZERO
    buys: int = 0
    sells: int = 0
    winning_sells: int = 0
    dropped_orders: int = 0


@dataclass
class EngineResult:
    curve: list[tuple[date, float]]
    trades: list[TradeRec]
    totals: Totals
    final_value: Decimal
    liquidation_value: Decimal   # valore finale al netto di costi e imposte se si vendesse tutto
    days_braking: int
    positions_at_end: int


class BacktestContext(StrategyContext):
    """La strategia vede lo stato simulato e lo storico fino al giorno simulato, mai oltre."""

    def __init__(self, engine: "BacktestEngine", today: date):
        self.engine, self.today = engine, today

    def quantity(self, symbol: str) -> Decimal:
        h = self.engine.holdings.get(symbol)
        return h.qty if h else ZERO

    def cash(self) -> Decimal:
        return self.engine.cash

    def history(self, symbol: str, start: date, end: date) -> list:
        s = self.engine.series.get(symbol)
        if s is None:
            return []
        end = min(end, self.today)
        lo = bisect_right(s.dates, start - timedelta(days=1))
        hi = bisect_right(s.dates, end)
        return s.rows[lo:hi]

    def history_count(self, symbol: str) -> int:
        s = self.engine.series.get(symbol)
        return s.idx_le(self.today) + 1 if s else 0


class BacktestEngine:
    def __init__(self, strategy: BaseStrategy, symbols: list[str], instruments: dict[str, InstrumentInfo],
                 series: dict[str, Series], fx: dict[str, Series], costs: Costs, start: date, end: date,
                 capital: Decimal, progress: Callable[[int], None] | None = None):
        self.strategy = strategy
        self.symbols = symbols
        self.instruments = instruments
        self.series = series
        self.fx = fx
        self.costs = costs
        self.start, self.end = start, end
        self.cash = capital
        self.holdings: dict[str, Holding] = {}
        self.lots: list[LossLot] = []
        self.pending: list[PendingOrder] = []
        self.trades: list[TradeRec] = []
        self.totals = Totals()
        self.progress = progress
        self._lot_id = 0

    # ── Prezzi e cambi ────────────────────────────────────────────────────────

    def calendar(self) -> list[date]:
        days: set[date] = set()
        for sym in self.symbols:
            s = self.series.get(sym)
            if s:
                days.update(d for d in s.dates if self.start <= d <= self.end)
        return sorted(days)

    def fx_rate(self, currency: str, d: date, at_open: bool = False) -> Decimal | None:
        if currency == "EUR":
            return Decimal("1")
        s = self.fx.get(currency)
        if s is None:
            return None
        if at_open:
            row = s.row_on(d)
            if row and row.open:
                return Decimal(str(row.open))
        v = s.close_le(d, STALE_DAYS)
        return Decimal(str(v)) if v else None

    def price_eur(self, symbol: str, d: date) -> Decimal | None:
        info = self.instruments.get(symbol)
        s = self.series.get(symbol)
        if info is None or s is None:
            return None
        close = s.close_le(d, STALE_DAYS)
        fx = self.fx_rate(info.currency, d)
        if close is None or not fx:
            return None
        return Decimal(str(close)) / fx

    def positions_value(self, d: date) -> Decimal:
        total = ZERO
        for sym, h in self.holdings.items():
            if h.qty > 0:
                info = self.instruments[sym]
                close = self.series[sym].close_le(d)
                fx = self.fx_rate(info.currency, d)
                if close is not None and fx:
                    total += h.qty * Decimal(str(close)) / fx
        return total

    # ── Simulazione ───────────────────────────────────────────────────────────

    def run(self) -> EngineResult:
        cal = self.calendar()
        if not cal:
            raise ValueError("Nessun prezzo disponibile nel periodo scelto")
        curve: list[tuple[date, float]] = []
        window: deque[tuple[date, Decimal]] = deque()
        braking = False
        days_braking = 0
        stamp_accrued = ZERO
        prev_day: date | None = None
        prev_value = ZERO
        last_pct = -1

        for i, d in enumerate(cal):
            self._dividends(d)
            self._execute_pending(d)

            pv = self.positions_value(d)
            # Bollo pro rata: ogni giorno di calendario vale il controvalore dell'ultimo giorno noto
            day = (prev_day + timedelta(days=1)) if prev_day else d
            while day <= d:
                if day.month == 1 and day.day == 1 and stamp_accrued > 0:
                    self._charge_stamp(day, stamp_accrued, day.year - 1)
                    stamp_accrued = ZERO
                value = pv if day == d else prev_value
                stamp_accrued += value * self.costs.stamp_rate / days_in_year(day.year)
                day += timedelta(days=1)
            prev_day, prev_value = d, pv

            equity = self.cash + pv
            curve.append((d, float(equity)))
            # Massimo degli ultimi 12 mesi (coda monotona: in testa sempre il massimo della finestra)
            while window and window[-1][1] <= equity:
                window.pop()
            window.append((d, equity))
            while window[0][0] <= d - timedelta(days=BRAKE_WINDOW_DAYS):
                window.popleft()
            braking = brake_state([window[0][1], equity], braking)
            days_braking += braking

            next_day = cal[i + 1] if i + 1 < len(cal) else None
            if next_day is not None and self.strategy.should_run_today(d, next_day):
                self._signal(d, braking)

            pct = int((i + 1) * 100 / len(cal))
            if self.progress and pct != last_pct:
                last_pct = pct
                self.progress(pct)

        last = cal[-1]
        if stamp_accrued > 0:
            self._charge_stamp(last, stamp_accrued, last.year)
        final = eur(self.cash + self.positions_value(last))
        curve[-1] = (last, float(final))
        return EngineResult(curve, self.trades, self.totals, final, self._liquidation_value(last),
                            days_braking, sum(1 for h in self.holdings.values() if h.qty > 0))

    def _signal(self, d: date, braking: bool) -> None:
        ups = []
        for sym in self.symbols:
            info = self.instruments.get(sym)
            price = self.price_eur(sym, d)
            ok = (price is not None and price > 0 and info is not None
                  and (info.type, info.market) in self.costs.commissions)
            ups.append(UniversePrice(sym, None, price if ok else ZERO, "EUR", ok))
        decisions = self.strategy.generate_decisions(BacktestContext(self, d), ups, braking)

        prices = {up.symbol: up.price for up in ups if up.available}
        total = self.cash + sum((h.qty * prices[s] for s, h in self.holdings.items() if s in prices), ZERO)
        waiting = {o.symbol for o in self.pending}
        for dec in decisions:
            if dec.action not in ("buy", "sell") or dec.symbol not in prices or dec.symbol in waiting:
                continue
            held = self.holdings.get(dec.symbol, Holding()).qty
            qty, err = order_quantity(dec.action, dec.target_weight, held, held, prices[dec.symbol], total)
            if not err:
                self.pending.append(PendingOrder(dec.symbol, dec.action, qty, dec.reason_it, d))

    def _execute_pending(self, d: date) -> None:
        if not self.pending:
            return
        keep = []
        for side in ("sell", "buy"):  # prima le vendite, che liberano liquidità
            for order in [o for o in self.pending if o.side == side]:
                row = self.series[order.symbol].row_on(d)
                if row is None:
                    order.waited += 1
                    if order.waited < PENDING_MAX_DAYS:
                        keep.append(order)
                    else:
                        self.totals.dropped_orders += 1
                    continue
                price = Decimal(str(row.open or row.close))
                if side == "sell":
                    self._sell(d, order, price)
                else:
                    self._buy(d, order, price)
        self.pending = keep

    def _amounts(self, info: InstrumentInfo, side: str, qty: Decimal, price: Decimal, fx: Decimal):
        conv = to_eur(qty * price, info.currency, fx, self.costs.fx_spread, side)
        gross = eur(conv.amount_eur)
        rule = self.costs.commissions[(info.type, info.market)]
        comm = commission(gross, rule.fixed, rule.pct, rule.minimum)
        tobin = tobin_tax(info.type, info.country, side, gross, self.costs.tobin_rate)
        return gross, comm, tobin

    def _buy(self, d: date, order: PendingOrder, price: Decimal) -> None:
        info = self.instruments[order.symbol]
        fx = self.fx_rate(info.currency, d, at_open=True)
        if not fx:
            self.totals.dropped_orders += 1
            return
        qty = order.qty
        gross, comm, tobin = self._amounts(info, "buy", qty, price, fx)
        # Se la liquidità non basta (prezzo di apertura diverso dalla chiusura) si riduce la quantità
        for _ in range(5):
            if gross + comm + tobin <= self.cash or qty <= 0:
                break
            qty = floor_qty(qty * self.cash / (gross + comm + tobin))
            if qty > 0:
                gross, comm, tobin = self._amounts(info, "buy", qty, price, fx)
        while qty > 0 and gross + comm + tobin > self.cash:
            qty -= 1
            if qty > 0:
                gross, comm, tobin = self._amounts(info, "buy", qty, price, fx)
        if qty <= 0:
            self.totals.dropped_orders += 1
            return
        net = gross + comm + tobin
        self.cash -= net
        h = self.holdings.setdefault(order.symbol, Holding())
        h.qty += qty
        h.cost_gross += gross
        h.cost_fiscal += gross + comm
        t = self.totals
        t.commissions += comm
        t.tobin += tobin
        t.bought_eur += gross
        t.buys += 1
        self.trades.append(TradeRec(d, order.symbol, "buy", qty, price, info.currency, gross, comm + tobin, ZERO,
                                    -net, None, order.reason))

    def _sale(self, d: date, symbol: str, qty: Decimal, price: Decimal, fx: Decimal, lots: list[LossLot]):
        """Importi di una vendita (non modifica lo stato): lordo, commissione, imposta, dettaglio fiscale."""
        info = self.instruments[symbol]
        h = self.holdings[symbol]
        gross, comm, _ = self._amounts(info, "sell", qty, price, fx)
        fraction = qty / h.qty
        realized_gross = eur(gross - h.cost_gross * fraction)
        realized_fiscal = eur(gross - comm - h.cost_fiscal * fraction)
        detail = compute_sale_tax(realized_fiscal, self.costs.tax_rules[info.fiscal_category], lots, d)
        return gross, comm, detail, realized_gross, fraction

    def _sell(self, d: date, order: PendingOrder, price: Decimal) -> None:
        info = self.instruments[order.symbol]
        h = self.holdings.get(order.symbol)
        fx = self.fx_rate(info.currency, d, at_open=True)
        qty = min(order.qty, h.qty) if h else ZERO
        if qty <= 0 or not fx:
            self.totals.dropped_orders += 1
            return
        gross, comm, detail, realized_gross, fraction = self._sale(d, order.symbol, qty, price, fx, self.lots)
        for lot_id, amount in detail.usages:
            for lot in self.lots:
                if lot.entry_id == lot_id:
                    lot.remaining -= amount
        if detail.loss_added > 0:
            self._lot_id += 1
            self.lots.append(LossLot(self._lot_id, d, detail.loss_expiry, detail.loss_added, info.fiscal_category))
        net = gross - comm - detail.tax
        self.cash += net
        h.cost_gross -= h.cost_gross * fraction
        h.cost_fiscal -= h.cost_fiscal * fraction
        h.qty -= qty
        t = self.totals
        t.commissions += comm
        t.capital_gain_tax += detail.tax
        t.sold_eur += gross
        t.sells += 1
        t.winning_sells += realized_gross > 0
        self.trades.append(TradeRec(d, order.symbol, "sell", qty, price, info.currency, gross, comm, detail.tax,
                                    net, realized_gross, order.reason))

    def _dividends(self, d: date) -> None:
        for sym, h in self.holdings.items():
            if h.qty <= 0:
                continue
            row = self.series[sym].row_on(d)
            if row is None or not row.dividend:
                continue
            info = self.instruments[sym]
            fx = self.fx_rate(info.currency, d)
            if not fx:
                continue
            rule = self.costs.tax_rules[info.fiscal_category]
            wh = self.costs.withholding.get(info.country or "", ZERO) \
                if info.type == "stock" and info.country and info.country != "IT" else ZERO
            amount = Decimal(str(row.dividend))
            a = dividend_breakdown(h.qty, h.qty * amount, info.currency, fx, self.costs.fx_spread, wh,
                                   rule.rate, rule.base_factor)
            self.cash += a.net_eur
            t = self.totals
            t.dividends_gross += a.gross_eur
            t.withholding += a.withholding_eur
            t.dividend_tax += a.tax_eur
            self.trades.append(TradeRec(d, sym, "dividend", h.qty, amount, info.currency, a.gross_eur, ZERO,
                                        a.withholding_eur + a.tax_eur, a.net_eur, None,
                                        f"Dividendo {amount:.4f} {info.currency} per azione (stacco)"))

    def _charge_stamp(self, d: date, accrued: Decimal, year: int) -> None:
        amount = eur(accrued)
        if amount <= 0:
            return
        self.cash -= amount
        self.totals.stamp += amount
        self.trades.append(TradeRec(d, "—", "stamp", ZERO, ZERO, "EUR", ZERO, ZERO, amount, -amount, None,
                                    f"Imposta di bollo {year} (0,2% annuo pro rata sul controvalore)"))

    def _liquidation_value(self, d: date) -> Decimal:
        """Liquidità se si vendesse tutto alla chiusura dell'ultimo giorno, con commissioni e imposte."""
        cash = self.cash
        lots = [LossLot(lot.entry_id, lot.origin, lot.expiry, lot.remaining, lot.fiscal_category) for lot in self.lots]
        for sym, h in self.holdings.items():
            if h.qty <= 0:
                continue
            info = self.instruments[sym]
            close = self.series[sym].close_le(d)
            fx = self.fx_rate(info.currency, d)
            if close is None or not fx:
                continue
            gross, comm, detail, _, _ = self._sale(d, sym, h.qty, Decimal(str(close)), fx, lots)
            for lot_id, amount in detail.usages:
                for lot in lots:
                    if lot.entry_id == lot_id:
                        lot.remaining -= amount
            cash += gross - comm - detail.tax
        return eur(cash)


# ── Risultati ─────────────────────────────────────────────────────────────────

def benchmark_curve(bench: Series | None, bench_fx: Series | None, cal: list[date],
                    capital: float) -> list[tuple[date, float]]:
    """Valore di `capital` investito nell'indice (solo prezzo, convertito in EUR) dal primo giorno."""
    if bench is None:
        return []
    out, base = [], None
    for d in cal:
        close = bench.close_le(d, STALE_DAYS)
        fx = bench_fx.close_le(d, STALE_DAYS) if bench_fx is not None else 1.0
        if close is None or not fx:
            continue
        v = close / fx
        if base is None:
            base = v
        out.append((d, capital * v / base))
    return out


def build_results(res: EngineResult, bench: list[tuple[date, float]], bench_label: str | None,
                  capital: Decimal, split: date | None, risk_free: float) -> dict:
    curve = res.curve
    net_curve = curve[:-1] + [(curve[-1][0], float(res.liquidation_value))]
    years = max((curve[-1][0] - curve[0][0]).days / 365.25, 1 / 365.25)
    avg_equity = sum(v for _, v in curve) / len(curve)
    t = res.totals

    def block(c, b):
        out = {"strategy": metrics.summary(c, risk_free)}
        if b:
            out["benchmark"] = metrics.summary(b, risk_free)
        return out

    periods = {"full": block(net_curve, bench)}
    if split:
        periods["in_sample"] = block(metrics.slice_curve(curve, end=split), metrics.slice_curve(bench, end=split))
        periods["out_of_sample"] = block(metrics.slice_curve(net_curve, start=split),
                                         metrics.slice_curve(bench, start=split))

    bench_map = dict(bench)
    weekly = metrics.weekly(curve)
    base = float(capital)
    chart = [{"date": d.isoformat(), "value": round(v, 2), "pct": round((v / base - 1) * 100, 3),
              "bench_pct": round((bench_map[d] / base - 1) * 100, 3) if d in bench_map else None}
             for d, v in weekly]

    return {
        "periods": periods,
        "benchmark_label": bench_label,
        "final_value": str(res.final_value),
        "liquidation_value": str(res.liquidation_value),
        "trades": t.buys + t.sells,
        "buys": t.buys,
        "sells": t.sells,
        "win_rate": (t.winning_sells / t.sells) if t.sells else None,
        "turnover": float(min(t.bought_eur, t.sold_eur)) / avg_equity / years if avg_equity else None,
        "costs": {
            "commissions": str(t.commissions),
            "tobin": str(t.tobin),
            "capital_gain_tax": str(t.capital_gain_tax),
            "dividends_gross": str(t.dividends_gross),
            "withholding": str(t.withholding),
            "dividend_tax": str(t.dividend_tax),
            "stamp": str(t.stamp),
        },
        "dropped_orders": t.dropped_orders,
        "days_braking": res.days_braking,
        "positions_at_end": res.positions_at_end,
        "chart": chart,
    }


# ── Esecuzione in background ──────────────────────────────────────────────────

def load_costs(db: Session) -> Costs:
    return Costs(
        commissions={(r.instrument_type, r.market): CommRule(r.fixed_eur, r.pct, r.minimum_eur)
                     for r in db.scalars(select(CommissionRule))},
        tax_rules={r.fiscal_category: TaxInfo(r.rate, r.base_factor, r.gains_kind, r.losses_kind)
                   for r in db.scalars(select(TaxRule))},
        withholding={r.country: r.rate for r in db.scalars(select(WithholdingRate))},
        tobin_rate=settings.get_decimal(db, "tobin_rate"),
        fx_spread=settings.get_decimal(db, "fx_spread"),
        stamp_rate=settings.get_decimal(db, "stamp_duty_rate"),
    )


def load_series(db: Session, symbol: str, start: date, end: date) -> Series | None:
    rows = db.execute(
        select(PriceHistoryCache.date, PriceHistoryCache.open, PriceHistoryCache.high, PriceHistoryCache.low,
               PriceHistoryCache.close, PriceHistoryCache.volume, PriceHistoryCache.dividend,
               PriceHistoryCache.split_ratio)
        .where(PriceHistoryCache.symbol == symbol, PriceHistoryCache.date >= start, PriceHistoryCache.date <= end)
        .order_by(PriceHistoryCache.date)
    ).all()
    return Series([DayRow(*r) for r in rows]) if rows else None


def warnings_for(db: Session, run: BacktestRun, symbols_missing: list[str]) -> list[str]:
    out = [
        "Le liste dei titoli sono quelle di oggi: mancano i titoli usciti dagli indici negli anni passati "
        "(spesso perché andati male). Il risultato storico è quindi ottimistico.",
        "L'indice di confronto conta solo il prezzo, senza dividendi; il portafoglio invece li incassa.",
    ]
    count = db.query(BacktestRun).filter(BacktestRun.strategy_type == run.strategy_type).count()
    if count > OVERFITTING_WARNING:
        out.append(f"Hai già fatto {count} backtest di {run.strategy_type}: provando molte varianti si finisce "
                   "per scegliere i parametri che vanno bene sul passato, non quelli che funzioneranno.")
    if symbols_missing:
        out.append(f"Titoli esclusi perché senza dati: {', '.join(symbols_missing[:10])}"
                   + ("…" if len(symbols_missing) > 10 else "") + ".")
    return out


def execute(db: Session, run: BacktestRun, fetch: bool = True) -> None:
    """Esegue un backtest già registrato e ne salva risultati e operazioni."""
    from .universes import get_symbols
    params = json.loads(run.params_json)
    universe_list = params.get("universe_list", "")
    symbols = get_symbols(db, [universe_list])
    bench_sym, bench_label, bench_ccy = BENCHMARKS.get(universe_list, (None, None, "EUR"))

    instruments = {i.symbol: InstrumentInfo(i.symbol, i.type, i.market, i.country, i.currency, i.fiscal_category)
                   for i in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))}
    currencies = {i.currency for i in instruments.values()} | {bench_ccy}
    extra = [fx_symbol(c) for c in currencies if c != "EUR"] + ([bench_sym] if bench_sym else [])
    if fetch:
        for sym in extra:
            try:
                fetch_history(db, sym)
            except Exception as exc:  # noqa: BLE001 - senza indice o cambio aggiornato si usa la cache
                db.rollback()
                log.warning("Backtest: %s non aggiornato (%s)", sym, exc)

    load_from = run.start_date - timedelta(days=LOOKBACK_DAYS)
    series = {}
    for sym in symbols:
        s = load_series(db, sym, load_from, run.end_date)
        if s is not None and sym in instruments:
            series[sym] = s
    missing = [s for s in symbols if s not in series]
    if len(series) < 0.75 * len(symbols):
        raise ValueError(f"Dati storici disponibili solo per {len(series)} titoli su {len(symbols)}: "
                         "apri il portafoglio e attendi la preparazione dei dati.")
    fx = {c: load_series(db, fx_symbol(c), load_from, run.end_date) for c in currencies if c != "EUR"}
    fx = {c: s for c, s in fx.items() if s is not None}

    strategy = STRATEGY_CLASSES[run.strategy_type](None, params)
    last = {"pct": 0}

    def progress(pct: int) -> None:
        if pct >= last["pct"] + 2:
            last["pct"] = pct
            run.progress = min(pct, 99)
            db.commit()

    engine = BacktestEngine(strategy, symbols, instruments, series, fx, load_costs(db),
                            run.start_date, run.end_date, run.initial_capital, progress)
    res = engine.run()
    cal = [d for d, _ in res.curve]
    bench = benchmark_curve(load_series(db, bench_sym, load_from, run.end_date) if bench_sym else None,
                            fx.get(bench_ccy) if bench_ccy != "EUR" else None, cal, float(run.initial_capital))
    results = build_results(res, bench, bench_label, run.initial_capital, run.split_date,
                            float(params.get("risk_free", 0.02)))
    results["warnings"] = warnings_for(db, run, missing)
    results["first_day"] = cal[0].isoformat()

    db.add_all(BacktestTrade(run_id=run.id, day=t.day, symbol=t.symbol, side=t.side, quantity=t.qty,
                             price=t.price, currency=t.currency, gross_eur=t.gross_eur, costs_eur=t.costs_eur,
                             tax_eur=t.tax_eur, cash_delta_eur=t.cash_delta_eur, realized_eur=t.realized_eur,
                             reason=t.reason) for t in res.trades)
    run.results_json = json.dumps(results)
    run.status, run.progress, run.finished_at = "done", 100, utcnow()
    db.commit()


_worker_lock = threading.Lock()
_worker: threading.Thread | None = None


def create_run(db: Session, strategy_type: str, params: dict, start: date, end: date, capital: Decimal,
               split: date | None = None, config_id: int | None = None) -> BacktestRun:
    run = BacktestRun(strategy_config_id=config_id, strategy_type=strategy_type,
                      strategy_version=STRATEGY_VERSIONS.get(strategy_type, "1"), params_json=json.dumps(params),
                      start_date=start, end_date=end, split_date=split, initial_capital=capital,
                      status="queued", progress=0, created_at=utcnow())
    db.add(run)
    db.commit()
    start_worker()
    return run


def start_worker() -> None:
    """Un solo backtest alla volta (il Pi ha poca memoria): gli altri aspettano in coda."""
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_work, daemon=True, name="backtest")
        _worker.start()


def _work() -> None:
    from ..database import SessionLocal
    while True:
        with SessionLocal() as db:
            run = db.scalar(select(BacktestRun).where(BacktestRun.status.in_(("queued", "running")))
                            .order_by(BacktestRun.id))
            if run is None:
                return
            run.status, run.progress, run.message = "running", 0, None
            db.commit()
            try:
                execute(db, run)
            except Exception as exc:  # noqa: BLE001 - l'errore si mostra nella schermata
                db.rollback()
                log.exception("Backtest %s fallito", run.id)
                run = db.get(BacktestRun, run.id)
                run.status, run.message, run.finished_at = "error", str(exc), utcnow()
                db.commit()
