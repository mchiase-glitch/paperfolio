"""
Regole di rischio comuni (fase E2), uguali dal vivo e nel backtest.

- Dimensionamento: pesi uguali (predefinito), peso inverso alla volatilità a 60 giorni, oppure rischio
  fisso per operazione (quota del capitale che si accetta di perdere ÷ distanza dallo stop).
- Limiti: peso massimo per titolo, peso massimo per settore, numero massimo di titoli. Valgono sugli
  acquisti: un titolo (o un settore) che supera il limite perché è salito non viene venduto, così non si
  pagano commissioni per piccoli aggiustamenti. Gli ETF su indici sono esclusi: sono già diversificati.
- Stop facoltativi: fisso sotto il prezzo d'ingresso, trailing sotto il massimo raggiunto, sulla
  volatilità (k × ATR a 20 giorni sotto l'ingresso), temporale dopo N giorni di borsa.

Il prezzo d'ingresso è la chiusura (rettificata per gli split) del giorno dell'acquisto: dal vivo gli
ordini partono a ridosso della chiusura e così il livello dello stop è lo stesso nei due casi.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from .auto_rules import CASH_BUFFER
from .indicators import atr, volatility_annual

ZERO = Decimal("0")
ONE = Decimal("1")

SIZING_MODES = ("equal", "inverse_vol", "fixed_risk")
DEFAULT_MAX_WEIGHT = Decimal("0.10")
DEFAULT_MAX_SECTOR = Decimal("0.30")
DEFAULT_RISK = Decimal("0.01")
VOL_DAYS = 60
ATR_DAYS = 20
STOP_NOTE = "Stop automatico"  # inizio della nota degli ordini stop gestiti dai portafogli automatici


def _pct(v) -> str:
    return f"{float(v) * 100:.1f}%".replace(".", ",")


# ── Stop ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StopParams:
    fixed: Decimal = ZERO      # es. 0,10 = vendi se scende del 10% sotto il prezzo d'ingresso
    trailing: Decimal = ZERO   # es. 0,15 = vendi se scende del 15% sotto il massimo dall'ingresso
    atr_k: Decimal = ZERO      # es. 3 = vendi se scende di 3 ATR sotto il prezzo d'ingresso
    time_days: int = 0         # es. 20 = vendi dopo 20 giorni di borsa

    @classmethod
    def from_params(cls, params: dict) -> "StopParams":
        return cls(Decimal(str(params.get("stop_fixed_pct") or 0)), Decimal(str(params.get("stop_trailing_pct") or 0)),
                   Decimal(str(params.get("stop_atr_k") or 0)), int(params.get("stop_time_days") or 0))

    @property
    def has_price_stop(self) -> bool:
        return self.fixed > 0 or self.trailing > 0 or self.atr_k > 0

    @property
    def any(self) -> bool:
        return self.has_price_stop or self.time_days > 0


def atr_at(rows: list) -> float | None:
    """ATR a 20 giorni sulle righe giornaliere (l'ultima è il giorno di riferimento)."""
    rows = rows[-(ATR_DAYS + 1):]
    highs = [r.high if r.high is not None else r.close for r in rows]
    lows = [r.low if r.low is not None else r.close for r in rows]
    return atr(highs, lows, [r.close for r in rows], ATR_DAYS)


def stop_level(sp: StopParams, entry: float, highest: float, atr_entry: float | None) -> tuple[float, str] | None:
    """Livello dello stop (nella valuta di quotazione) e descrizione: se ce n'è più d'uno vale il più alto,
    cioè quello che scatta per primo."""
    levels = []
    if sp.fixed > 0:
        levels.append((entry * (1 - float(sp.fixed)), f"stop fisso {_pct(sp.fixed)} sotto l'ingresso {entry:.2f}"))
    if sp.atr_k > 0 and atr_entry:
        levels.append((entry - float(sp.atr_k) * atr_entry,
                       f"stop sulla volatilità {float(sp.atr_k):g} × ATR ({atr_entry:.2f}) sotto l'ingresso {entry:.2f}"))
    if sp.trailing > 0:
        levels.append((highest * (1 - float(sp.trailing)),
                       f"trailing stop {_pct(sp.trailing)} sotto il massimo {highest:.2f}"))
    levels = [lv for lv in levels if lv[0] > 0]
    return max(levels, key=lambda x: x[0]) if levels else None


def entry_reference(ctx, symbol: str, entry: date) -> tuple[float, float, float | None] | None:
    """(prezzo d'ingresso, massimo delle chiusure dall'ingresso a oggi, ATR al giorno d'ingresso)."""
    dates, closes, i = ctx.closes(symbol)
    if i < 0:
        return None
    # Dal vivo la riga del giorno d'acquisto può non essere ancora nello storico: si usa l'ultima chiusura nota
    k = min(bisect_left(dates, entry), i)
    rows = ctx.history(symbol, date.fromordinal(entry.toordinal() - 45), entry)
    return closes[k], max(closes[k:i + 1]), atr_at(rows) if rows else None


def stop_distance(sp: StopParams, ctx, symbol: str) -> float | None:
    """Distanza (quota del prezzo) dello stop più vicino se si comprasse oggi: serve al rischio fisso."""
    dates, closes, i = ctx.closes(symbol)
    if i < 0:
        return None
    price = closes[i]
    a = None
    if sp.atr_k > 0:
        rows = ctx.history(symbol, date.fromordinal(ctx.today.toordinal() - 45), ctx.today)
        a = atr_at(rows) if rows else None
    lv = stop_level(sp, price, price, a)
    return 1 - lv[0] / price if lv and price > 0 else None


# ── Dimensionamento e limite per titolo ───────────────────────────────────────

def _volatility(ctx, symbol: str) -> float | None:
    _, closes, i = ctx.closes(symbol)
    if i < VOL_DAYS:
        return None
    v = volatility_annual(closes[i - VOL_DAYS:i + 1], VOL_DAYS)
    return v if v and v > 0 else None


def _mean_inverse_vol(ctx, universe: list) -> float | None:
    """Media di 1/volatilità sui titoli dell'universo (calcolata una volta per controllo)."""
    cache = ctx.__dict__.setdefault("_inverse_vol", {})
    key = id(universe)
    if key not in cache:
        inv = [1 / v for up in universe if up.available and up.instrument_type == "stock"
               for v in [_volatility(ctx, up.symbol)] if v]
        cache[key] = sum(inv) / len(inv) if inv else None
    return cache[key]


def sized_weight(params: dict, max_weight: Decimal, ctx, up, base: Decimal, universe: list) -> tuple[Decimal, str]:
    """Peso obiettivo dopo dimensionamento e limite per titolo, con la spiegazione per il registro ("" se
    resta il peso normale della strategia).

    - inverse_vol: peso normale × (1/volatilità del titolo) ÷ (media di 1/volatilità dell'universo): i titoli
      meno volatili della media pesano di più, i più volatili di meno;
    - fixed_risk: rischio per operazione ÷ distanza dallo stop, mai oltre il peso normale della strategia.
    """
    if base <= ZERO:
        return base, ""
    w, notes = base, []
    mode = params.get("sizing", "equal")
    if mode == "inverse_vol" and up.instrument_type == "stock":
        v, mean_inv = _volatility(ctx, up.symbol), _mean_inverse_vol(ctx, universe)
        if v and mean_inv:
            w = base * Decimal(str(round((1 / v) / mean_inv, 6)))
            notes.append(f"volatilità {_pct(v)} contro {_pct(1 / mean_inv)} della media: peso {_pct(base)} → {_pct(w)}")
    elif mode == "fixed_risk" and up.instrument_type == "stock":  # gli ETF restano alla loro quota
        sp = StopParams.from_params(params)
        d = stop_distance(sp, ctx, up.symbol) if sp.has_price_stop else None
        if d:
            risk = Decimal(str(params.get("risk_per_trade", DEFAULT_RISK)))
            w = min(base, risk / Decimal(str(round(d, 6))))
            notes.append(f"rischio {_pct(risk)} ÷ distanza dallo stop {_pct(d)}: peso {_pct(w)}"
                         + (f" (non oltre {_pct(base)})" if w == base else ""))
    if up.instrument_type == "stock" and w > max_weight:
        w = max_weight
        notes.append(f"limitato a {_pct(max_weight)} per titolo")
    return w, "; ".join(notes)


# ── Limiti sul portafoglio: settore e numero di titoli ────────────────────────

def apply_limits(params: dict, ctx, decisions: list, universe: list, total: Decimal,
                 sectors: dict[str, str | None], min_order: Decimal = ZERO) -> list:
    """Riduce o blocca gli acquisti che porterebbero un settore oltre il limite o i titoli oltre il numero
    massimo. Gli acquisti si esaminano nell'ordine della strategia (di solito dal migliore)."""
    max_sector = Decimal(str(params.get("max_sector", DEFAULT_MAX_SECTOR)))
    max_titles = int(params.get("max_titles") or 0)
    if (max_sector >= ONE and max_titles <= 0) or total <= ZERO:
        return decisions
    prices = {up.symbol: up for up in universe if up.available and up.price > ZERO}
    closing = {d.symbol for d in decisions if d.action == "sell" and not d.target_weight}
    owned = {up.symbol for up in universe if ctx.quantity(up.symbol) > ZERO} - closing
    weight = {s: ctx.quantity(s) * prices[s].price / total for s in owned if s in prices}
    sector_w: dict[str, Decimal] = {}
    for s, w in weight.items():
        if prices[s].instrument_type == "stock" and sectors.get(s):
            sector_w[sectors[s]] = sector_w.get(sectors[s], ZERO) + w
    count = len(owned)

    from .strategies.base import Decision
    out = []
    for d in decisions:
        up = prices.get(d.symbol)
        if d.action != "buy" or up is None or not d.target_weight:
            out.append(d)
            continue
        new_position = d.symbol not in owned
        if new_position and max_titles > 0 and count >= max_titles:
            out.append(Decision(d.symbol, "hold", None, f"{d.reason_it} — non comprato: già {count} titoli in "
                                                        f"portafoglio (massimo {max_titles})", d.signal_data))
            continue
        w, note = d.target_weight, ""
        sec = sectors.get(d.symbol) if up.instrument_type == "stock" else None
        cur = weight.get(d.symbol, ZERO)
        if sec and max_sector < ONE:
            add = max(w * CASH_BUFFER - cur, ZERO)
            room = max_sector - sector_w.get(sec, ZERO)
            if add > room:
                w = (cur + max(room, ZERO)) / CASH_BUFFER
                add = max(w * CASH_BUFFER - cur, ZERO)
                if add * total < max(min_order, up.price) or room <= ZERO:
                    out.append(Decision(d.symbol, "hold", None,
                                        f"{d.reason_it} — non comprato: settore {sec} già al "
                                        f"{_pct(sector_w.get(sec, ZERO))} (limite {_pct(max_sector)})", d.signal_data))
                    continue
                note = f" — ridotto a {_pct(w)} per il limite del {_pct(max_sector)} sul settore {sec}"
            sector_w[sec] = sector_w.get(sec, ZERO) + add
        if new_position:
            count += 1
            owned.add(d.symbol)
        out.append(replace(d, target_weight=w, reason_it=d.reason_it + note) if note else d)
    return out


def needs_sectors(params: dict) -> bool:
    return Decimal(str(params.get("max_sector", DEFAULT_MAX_SECTOR))) < ONE
