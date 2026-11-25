"""
P7 – Portafoglio combinato.

Contiene più strategie scelte tra P1–P6 (default P2, P4 e P5), ciascuna con una quota del capitale
(default uguali). Ogni strategia lavora sulla propria quota come se fosse un portafoglio a sé:
la quota tiene una liquidità e un numero di azioni "virtuali". Il portafoglio vero è uno solo:
liquidità, zainetto, imposte e bollo sono comuni.

A ogni esecuzione:
1. le quote vengono riallineate al portafoglio vero: ordini non eseguiti, commissioni, imposte,
   dividendi e bollo finiscono nelle quote in proporzione;
2. una volta l'anno (mese scelto, default gennaio) le quote tornano alle percentuali stabilite;
3. ogni strategia che deve operare oggi decide sulla propria quota;
4. gli ordini sullo stesso titolo si compensano: se una strategia compra 100 ENI e un'altra ne
   vende 60, parte un solo acquisto da 40;
5. limite di rischio sul portafoglio intero: nessuna azione oltre il 10% del totale, sommando le strategie
   (gli ETF su indici sono esclusi dal limite: sono già diversificati).

Parametri: sleeves ([{"type": "P2", "share": 0.333, "params": {...}}, ...]), rebalance_month (1),
max_weight (0.10).
"""
from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from ..auto_rules import CASH_BUFFER, floor_qty, order_quantity
from .base import BaseStrategy, Decision, StrategyContext, UniversePrice, period_key

ZERO = Decimal("0")
ONE = Decimal("1")
FREQ_ORDER = {"daily": 0, "monthly": 1, "annual": 2}

DEFAULT_SLEEVES = [
    {"type": "P2", "share": 1 / 3, "params": {"universe_list": "ftse_mib", "sma_months": 10}},
    {"type": "P4", "share": 1 / 3, "params": {}},
    {"type": "P5", "share": 1 / 3, "params": {}},
]


class SleeveContext(StrategyContext):
    """La quota di una strategia: azioni e liquidità virtuali, storico e bilanci del portafoglio vero."""

    def __init__(self, ctx: StrategyContext, sleeve: dict):
        self.ctx, self.sleeve, self.today = ctx, sleeve, ctx.today

    def quantity(self, symbol: str) -> Decimal:
        return Decimal(self.sleeve["qty"].get(symbol, "0"))

    def cash(self) -> Decimal:
        return Decimal(self.sleeve["cash"])

    def history(self, symbol, start, end):
        return self.ctx.history(symbol, start, end)

    def history_count(self, symbol):
        return self.ctx.history_count(symbol)

    def closes(self, symbol):
        return self.ctx.closes(symbol)

    def entry_date(self, symbol):
        return self.ctx.entry_date(symbol) if self.quantity(symbol) > 0 else None

    def fundamentals(self, symbol):
        return self.ctx.fundamentals(symbol)


class P7Combined(BaseStrategy):

    def __init__(self, config, params: dict):
        super().__init__(config, params)
        from . import STRATEGY_CLASSES  # import qui: il registro delle strategie include anche P7
        specs = params.get("sleeves") or DEFAULT_SLEEVES
        total_share = sum(float(s.get("share", 1)) for s in specs) or 1
        self.sleeves: list[tuple[str, BaseStrategy, Decimal]] = []
        seen: dict[str, int] = {}
        for spec in specs:
            t = spec["type"]
            if t not in STRATEGY_CLASSES or t == "P7":
                continue
            seen[t] = seen.get(t, 0) + 1
            name = t if seen[t] == 1 else f"{t}-{seen[t]}"
            share = Decimal(str(round(float(spec.get("share", 1)) / total_share, 6)))
            self.sleeves.append((name, STRATEGY_CLASSES[t](None, dict(spec.get("params") or {})), share))
        self.state: dict = {}
        self.needs_fundamentals = any(s.needs_fundamentals for _, s, _ in self.sleeves)
        unavailable = [n for n, s, _ in self.sleeves if s.backtest_unavailable]
        if unavailable:
            self.backtest_unavailable = (f"Il portafoglio contiene {', '.join(unavailable)}, che non ha backtest: "
                                         "la fonte non ha i bilanci storici.")

    # ── Caratteristiche ───────────────────────────────────────────────────────

    @property
    def frequency(self) -> str:
        return "daily"  # decide da sé quale strategia deve operare oggi

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        return any(s.should_run_today(today, next_day) for _, s, _ in self.sleeves)

    def universe_lists(self) -> list[str]:
        return list(dict.fromkeys(name for _, s, _ in self.sleeves for name in s.universe_lists()))

    def extra_tradeable(self) -> list[str]:
        return list(dict.fromkeys(x for _, s, _ in self.sleeves for x in s.extra_tradeable()))

    def reference_symbols(self) -> list[str]:
        return list(dict.fromkeys(x for _, s, _ in self.sleeves for x in s.reference_symbols()))

    def load_state(self, state_json: str | None) -> None:
        self.state = json.loads(state_json) if state_json else {}

    def dump_state(self) -> str | None:
        return json.dumps(self.state)

    # ── Esecuzione ────────────────────────────────────────────────────────────

    def generate_decisions(self, ctx: StrategyContext, universe_prices: list[UniversePrice],
                           drawdown_braking: bool) -> list[Decision]:
        prices = {up.symbol: up.price for up in universe_prices if up.available and up.price > ZERO}
        max_weight = self._param_decimal("max_weight", "0.10")
        books = self._books(ctx)
        self._reconcile(ctx, books, prices)
        notes = self._rebalance_shares(ctx, books, prices)

        next_day = getattr(ctx, "next_day", None)
        force = getattr(ctx, "force_all", False)
        last = self.state.setdefault("last_run", {})
        requested: dict[str, list[tuple[str, Decimal, str]]] = {}  # simbolo → [(quota, variazione, motivo)]
        for name, strategy, _ in self.sleeves:
            due = force or strategy.should_run_today(ctx.today, next_day)
            period = period_key(strategy.frequency, ctx.today)
            if not due or (last.get(name) == period and not force):
                continue
            if not force:
                last[name] = period
            book = books[name]
            sctx = SleeveContext(ctx, book)
            sleeve_total = sctx.cash() + sum((sctx.quantity(s) * p for s, p in prices.items()), ZERO)
            # Ogni strategia vede solo il proprio universo (più i titoli che la sua quota possiede già)
            lists, extra = set(strategy.universe_lists()), set(strategy.extra_tradeable())
            own = [up for up in universe_prices
                   if lists & set(up.groups) or up.symbol in extra or up.symbol in book["qty"]] \
                if lists or extra else list(universe_prices)
            for dec in strategy.generate_decisions(sctx, own, drawdown_braking and strategy.uses_drawdown_brake):
                if dec.action not in ("buy", "sell") or dec.symbol not in prices:
                    notes.append(Decision(dec.symbol, dec.action, None, f"[{name}] {dec.reason_it}", dec.signal_data))
                    continue
                held = sctx.quantity(dec.symbol)
                qty, err = order_quantity(dec.action, dec.target_weight, held, held, prices[dec.symbol], sleeve_total)
                if err:
                    notes.append(Decision(dec.symbol, "hold", None, f"[{name}] {dec.reason_it} — {err}"))
                    continue
                delta = qty if dec.action == "buy" else -qty
                if held + delta > 0:
                    book["qty"][dec.symbol] = str(held + delta)
                else:
                    book["qty"].pop(dec.symbol, None)
                book["cash"] = str(Decimal(book["cash"]) - delta * prices[dec.symbol])
                requested.setdefault(dec.symbol, []).append((name, delta, dec.reason_it))

        total = ctx.cash() + sum((ctx.quantity(s) * p for s, p in prices.items()), ZERO)
        etfs = {up.symbol for up in universe_prices if up.instrument_type != "stock"}
        decisions = self._net_orders(ctx, books, requested, prices, total, max_weight, etfs)
        self.state["books"] = books
        return decisions + notes

    def _books(self, ctx: StrategyContext) -> dict[str, dict]:
        """Quote virtuali; alla prima esecuzione la liquidità si divide secondo le percentuali."""
        books = self.state.get("books") or {}
        cash = ctx.cash()
        for name, _, share in self.sleeves:
            if name not in books:
                books[name] = {"cash": str((cash * share).quantize(Decimal("0.01"))), "qty": {}}
        for name in list(books):
            if name not in {n for n, _, _ in self.sleeves}:
                del books[name]
        if "rebalanced_year" not in self.state:
            self.state["rebalanced_year"] = ctx.today.year
        return books

    def _reconcile(self, ctx: StrategyContext, books: dict, prices: dict[str, Decimal]) -> None:
        """Le quote virtuali tornano a sommare esattamente il portafoglio vero."""
        symbols = {s for b in books.values() for s in b["qty"]} | {s for s in prices if ctx.quantity(s) > 0}
        biggest = max(self.sleeves, key=lambda x: x[2])[0]
        for sym in symbols:
            real = ctx.quantity(sym)
            virt = {n: Decimal(b["qty"].get(sym, "0")) for n, b in books.items()}
            total_virt = sum(virt.values(), ZERO)
            if total_virt == real:
                continue
            if total_virt <= 0:
                new = {n: ZERO for n in books}
                new[biggest] = real
            else:
                new = {n: floor_qty(q * real / total_virt) for n, q in virt.items()}
                rest = real - sum(new.values(), ZERO)
                if rest:
                    owner = max(virt, key=virt.get)
                    new[owner] += rest
            # Le azioni non comprate (o non vendute) restituiscono (o tolgono) liquidità alla quota che le aveva
            # chieste, al prezzo di oggi; il resto della differenza di cassa si ripartisce più sotto
            price = prices.get(sym)
            for n, q in new.items():
                if price is not None and q != virt[n]:
                    books[n]["cash"] = str(Decimal(books[n]["cash"]) + (virt[n] - q) * price)
                if q > 0:
                    books[n]["qty"][sym] = str(q)
                else:
                    books[n]["qty"].pop(sym, None)
        # La liquidità vera (costi, imposte, dividendi, bollo, ordini non eseguiti) si ripartisce in proporzione
        diff = ctx.cash() - sum((Decimal(b["cash"]) for b in books.values()), ZERO)
        if diff:
            values = {n: self._book_value(b, prices) for n, b in books.items()}
            tot = sum(values.values(), ZERO)
            shares = {n: (values[n] / tot if tot > 0 else s) for n, _, s in self.sleeves}
            for n, b in books.items():
                b["cash"] = str((Decimal(b["cash"]) + diff * shares[n]).quantize(Decimal("0.01")))

    def _rebalance_shares(self, ctx: StrategyContext, books: dict, prices: dict[str, Decimal]) -> list[Decision]:
        """Una volta l'anno le quote tornano alle percentuali stabilite, spostando liquidità virtuale."""
        month = int(self._param("rebalance_month", 1))
        if ctx.today.month != month or self.state.get("rebalanced_year") == ctx.today.year:
            return []
        self.state["rebalanced_year"] = ctx.today.year
        total = sum((self._book_value(b, prices) for b in books.values()), ZERO)
        parts = []
        for name, _, share in self.sleeves:
            b = books[name]
            before = self._book_value(b, prices)
            target = total * share
            b["cash"] = str((Decimal(b["cash"]) + target - before).quantize(Decimal("0.01")))
            parts.append(f"{name} {before / total * 100 if total else 0:.0f}% → {share * 100:.0f}%")
        return [Decision("—", "hold", None, "Ribilanciamento annuale delle quote: " + ", ".join(parts)
                         + ". Le strategie si adegueranno alle nuove quote nelle prossime esecuzioni.")]

    @staticmethod
    def _book_value(book: dict, prices: dict[str, Decimal]) -> Decimal:
        return Decimal(book["cash"]) + sum((Decimal(q) * prices.get(s, ZERO) for s, q in book["qty"].items()), ZERO)

    def _net_orders(self, ctx: StrategyContext, books: dict, requested: dict, prices: dict[str, Decimal],
                    total: Decimal, max_weight: Decimal, etfs: set[str]) -> list[Decision]:
        decisions = []
        for sym, parts in requested.items():
            price = prices[sym]
            current = ctx.quantity(sym)
            target = sum((Decimal(b["qty"].get(sym, "0")) for b in books.values()), ZERO)
            capped = ""
            if target > current and total > 0 and sym not in etfs:  # un ETF su indice è già diversificato
                cap = (total * max_weight / price).to_integral_value(rounding=ROUND_FLOOR)
                if target > cap:
                    target = max(cap, current)
                    capped = f" Limitato a {max_weight * 100:.0f}% del portafoglio per titolo."
            diff = target - current
            detail = "; ".join(f"[{n}] {'compra' if d > 0 else 'vende'} {abs(d):f}: {why}" for n, d, why in parts)
            if diff == 0:
                decisions.append(Decision(sym, "hold", None, f"{detail}. Ordini compensati: nessuna operazione."
                                                             f"{capped}"))
                continue
            net = "acquisto" if diff > 0 else "vendita"
            reason = f"{detail}. Ordine netto: {net} di {abs(diff):f}.{capped}" if len(parts) > 1 \
                else f"{detail}{'.' + capped if capped else ''}"
            # Peso obiettivo che fa calcolare al dimensionamento comune esattamente la quantità netta
            if diff > 0:
                w = (target * price + price / 2) / (total * CASH_BUFFER)
                decisions.append(Decision(sym, "buy", w, reason, {"net_qty": str(diff)}))
            else:
                w = max((target * price - price / 2) / total, ZERO) if target > 0 else ZERO
                decisions.append(Decision(sym, "sell", w, reason, {"net_qty": str(diff)}))
        return decisions
