"""
Indicatori tecnici usati dalle strategie automatiche.

Tutte le funzioni lavorano su liste Python di float (non Decimal) perché
il calcolo degli indicatori non richiede la precisione monetaria.
Restituiscono None dove i dati sono insufficienti.
"""
from __future__ import annotations

import math
from datetime import date


# ── Medie mobili ──────────────────────────────────────────────────────────────

def sma(prices: list[float], period: int) -> list[float | None]:
    """Media mobile semplice. I primi (period-1) valori sono None."""
    result: list[float | None] = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = sum(prices[i - period + 1: i + 1]) / period
    return result


def last_sma(prices: list[float], period: int) -> float | None:
    """Ultimo valore della SMA(period). None se i dati sono insufficienti."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def ema(prices: list[float], period: int) -> list[float | None]:
    """Media mobile esponenziale (EMA). Usata come base per RSI e ATR."""
    if not prices:
        return []
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * len(prices)
    # Prima EMA = SMA dei primi `period` valori
    if len(prices) < period:
        return result
    result[period - 1] = sum(prices[:period]) / period
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)  # type: ignore[operator]
    return result


# ── Dati mensili ──────────────────────────────────────────────────────────────

def monthly_closes(dates: list[date], closes: list[float]) -> list[tuple[date, float]]:
    """
    Restituisce (ultimo giorno di borsa del mese, chiusura) in ordine crescente.
    Utile per le strategie mensili come P2.
    """
    monthly: dict[tuple[int, int], tuple[date, float]] = {}
    for d, c in zip(dates, closes):
        key = (d.year, d.month)
        if key not in monthly or d > monthly[key][0]:
            monthly[key] = (d, c)
    return [(d, c) for _, (d, c) in sorted(monthly.items())]


def monthly_sma(dates: list[date], closes: list[float], period: int = 10) -> float | None:
    """
    Ultimo valore della SMA(period) calcolata sulle chiusure di fine mese.
    Usata da P2 (Faber 10 mesi).
    """
    mc = monthly_closes(dates, closes)
    if len(mc) < period:
        return None
    last_n = [c for _, c in mc[-period:]]
    return sum(last_n) / period


def last_monthly_close(dates: list[date], closes: list[float]) -> float | None:
    """Ultima chiusura di fine mese disponibile."""
    mc = monthly_closes(dates, closes)
    return mc[-1][1] if mc else None


# ── Rendimento e volatilità ───────────────────────────────────────────────────

def momentum_return(closes: list[float], lookback: int) -> float | None:
    """
    Rendimento totale su `lookback` barre: closes[-1] / closes[-(lookback+1)] - 1.
    Usato per il momentum 12-1.
    """
    if len(closes) < lookback + 1:
        return None
    base = closes[-(lookback + 1)]
    if base == 0:
        return None
    return closes[-1] / base - 1.0


def volatility_annual(closes: list[float], period: int = 60) -> float | None:
    """
    Volatilità annualizzata (deviazione standard dei log-rendimenti × √252).
    Usata dal dimensionamento a volatilità inversa.
    """
    if len(closes) < period + 1:
        return None
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(-period, 0)]
    n = len(log_returns)
    if n < 2:
        return None
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
    return math.sqrt(variance * 252)


# ── RSI ───────────────────────────────────────────────────────────────────────

def rsi(closes: list[float], period: int = 2) -> float | None:
    """
    RSI con smoothing di Wilder. Restituisce l'ultimo valore.
    Usato da P5 (fase C).
    """
    if len(closes) < period + 2:
        return None
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    # Primo avg = semplice
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


# ── ATR ───────────────────────────────────────────────────────────────────────

def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 20) -> float | None:
    """
    Average True Range (semplice, non smoothed). Ultimo valore.
    Usato da P5 e dallo stop a volatilità (fase C).
    """
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return None
    trs = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


# ── Prezzi split-adjusted ─────────────────────────────────────────────────────

def split_adjust(closes: list[float], split_ratios: list[float]) -> list[float]:
    """
    Restituisce i prezzi rettificati per gli split in modo da essere comparabili
    con l'ultimo prezzo disponibile.

    split_ratios[i] = fattore di split nel giorno i (1.0 se nessuno split,
    2.0 per uno split 2:1 nell'era moderna dove il prezzo post-split è già dimezzato).

    Algoritmo: si parte dal fondo e si accumula il fattore di divisione per ogni
    split avvenuto dopo il giorno i.
    """
    n = len(closes)
    if n != len(split_ratios):
        raise ValueError("closes e split_ratios devono avere la stessa lunghezza")
    result = list(closes)
    cum = 1.0
    for i in range(n - 1, -1, -1):
        result[i] = closes[i] / cum
        s = split_ratios[i]
        if s and s != 1.0:
            cum *= s
    return result
