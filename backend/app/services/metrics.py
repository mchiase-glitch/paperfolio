"""
Metriche di rendimento e rischio di una curva del valore (backtest e, in futuro, portafogli dal vivo).

Lavorano su float: servono per leggere i risultati, non per i conti in euro.
"""
from __future__ import annotations

import math
from datetime import date

TRADING_DAYS = 252


def cagr(curve: list[tuple[date, float]]) -> float | None:
    """Rendimento annuo composto tra il primo e l'ultimo punto."""
    if len(curve) < 2 or curve[0][1] <= 0:
        return None
    days = (curve[-1][0] - curve[0][0]).days
    if days <= 0:
        return None
    ratio = curve[-1][1] / curve[0][1]
    if ratio <= 0:
        return -1.0
    return ratio ** (365.25 / days) - 1


def daily_returns(curve: list[tuple[date, float]]) -> list[float]:
    return [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve)) if curve[i - 1][1] > 0]


def volatility(curve: list[tuple[date, float]]) -> float | None:
    """Deviazione standard annualizzata dei rendimenti giornalieri."""
    r = daily_returns(curve)
    if len(r) < 2:
        return None
    mean = sum(r) / len(r)
    var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var * TRADING_DAYS)


def sharpe(curve: list[tuple[date, float]], risk_free: float) -> float | None:
    """(rendimento medio annualizzato − tasso senza rischio) / volatilità."""
    r = daily_returns(curve)
    vol = volatility(curve)
    if not r or not vol:
        return None
    return (sum(r) / len(r) * TRADING_DAYS - risk_free) / vol


def max_drawdown(curve: list[tuple[date, float]]) -> dict:
    """Perdita massima dal picco e durata più lunga sotto un picco (in giorni di calendario).

    La durata va dal picco al ritorno sopra quel livello, oppure alla fine se non è mai tornato.
    """
    if not curve:
        return {"max_dd": None, "peak": None, "trough": None, "longest_days": None, "recovered": None}
    peak_v, peak_d = curve[0][1], curve[0][0]
    worst, worst_peak, worst_trough = 0.0, curve[0][0], curve[0][0]
    longest, longest_recovered, under = 0, True, False
    for d, v in curve:
        if v >= peak_v:
            if under:  # recuperato il picco precedente
                longest = max(longest, (d - peak_d).days)
                under = False
            peak_v, peak_d = v, d
            continue
        under = True
        dd = v / peak_v - 1 if peak_v > 0 else 0.0
        if dd < worst:
            worst, worst_peak, worst_trough = dd, peak_d, d
    if under and (curve[-1][0] - peak_d).days > longest:
        longest, longest_recovered = (curve[-1][0] - peak_d).days, False
    return {"max_dd": worst, "peak": worst_peak.isoformat(), "trough": worst_trough.isoformat(),
            "longest_days": longest, "recovered": longest_recovered}


def summary(curve: list[tuple[date, float]], risk_free: float) -> dict:
    dd = max_drawdown(curve)
    return {
        "start": curve[0][0].isoformat() if curve else None,
        "end": curve[-1][0].isoformat() if curve else None,
        "start_value": curve[0][1] if curve else None,
        "end_value": curve[-1][1] if curve else None,
        "total_return": (curve[-1][1] / curve[0][1] - 1) if len(curve) > 1 and curve[0][1] > 0 else None,
        "cagr": cagr(curve),
        "volatility": volatility(curve),
        "sharpe": sharpe(curve, risk_free),
        "max_drawdown": dd["max_dd"],
        "max_drawdown_peak": dd["peak"],
        "max_drawdown_trough": dd["trough"],
        "longest_drawdown_days": dd["longest_days"],
        "longest_drawdown_recovered": dd["recovered"],
    }


def slice_curve(curve: list[tuple[date, float]], start: date | None = None,
                end: date | None = None) -> list[tuple[date, float]]:
    return [(d, v) for d, v in curve if (start is None or d >= start) and (end is None or d < end)]


def weekly(curve: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Un punto per settimana (l'ultimo), più il primo: abbastanza per il grafico, leggero da inviare."""
    if not curve:
        return []
    out = [curve[0]]
    for i, (d, v) in enumerate(curve[1:], start=1):
        nxt = curve[i + 1][0] if i + 1 < len(curve) else None
        if nxt is None or nxt.isocalendar()[:2] != d.isocalendar()[:2]:
            out.append((d, v))
    return out
