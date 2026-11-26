"""
Regole comuni ai portafogli automatici dal vivo e al backtest.

Tenerle in un solo posto garantisce che il backtest simuli esattamente quello che
farebbe il portafoglio vero: stesso dimensionamento, stesso freno sul drawdown.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

ZERO = Decimal("0")

# Quota del capitale investita: il resto copre commissioni e piccoli scarti di prezzo
CASH_BUFFER = Decimal("0.98")
DRAWDOWN_ACTIVATE = Decimal("-0.20")   # -20%: attiva il freno
DRAWDOWN_RESUME = Decimal("-0.10")     # -10%: riprende gli acquisti
# Il massimo di riferimento è quello degli ultimi 12 mesi. Con il massimo "di sempre" un portafoglio
# rimasto in liquidità (vendite permesse, acquisti bloccati) non potrebbe più risalire e il freno
# resterebbe acceso per sempre.
BRAKE_WINDOW_DAYS = 365


def floor_qty(v: Decimal) -> Decimal:
    return v.to_integral_value(rounding=ROUND_FLOOR)


def drawdown(series: list[Decimal]) -> Decimal | None:
    """Distanza (negativa) dell'ultimo valore dal massimo della serie."""
    if not series:
        return None
    peak = max(series)
    if peak <= ZERO:
        return None
    return (series[-1] - peak) / peak


def brake_state(series: list[Decimal], currently_braking: bool) -> bool:
    """Freno acceso sotto il -20% dal massimo, spento quando si torna sopra il -10%.

    `series` = valori degli ultimi BRAKE_WINDOW_DAYS giorni, l'ultimo è quello attuale.
    """
    dd = drawdown(series)
    if dd is None:
        return currently_braking
    if not currently_braking and dd <= DRAWDOWN_ACTIVATE:
        return True
    if currently_braking and dd >= DRAWDOWN_RESUME:
        return False
    return currently_braking


DEFAULT_MIN_ORDER = Decimal("2500")  # sotto questa variazione non si ribilancia una posizione già aperta


def order_quantity(action: str, target_weight: Decimal | None, held: Decimal, free: Decimal,
                   price: Decimal, total: Decimal, min_order: Decimal = ZERO) -> tuple[Decimal, str | None]:
    """Azioni intere da comprare o vendere per avvicinarsi al peso obiettivo.

    price e total in EUR; free = azioni vendibili (non già impegnate in ordini di vendita).
    min_order: gli ordini di ribilanciamento (comprare ancora o vendere in parte un titolo già posseduto)
    sotto questo controvalore non si fanno, perché le commissioni minime li renderebbero troppo cari.
    Aprire una posizione nuova e vendere tutto si fa sempre.
    """
    if price <= ZERO:
        return ZERO, "prezzo non disponibile"
    current_value = held * price
    w = target_weight or ZERO
    if action == "buy":
        qty = floor_qty((total * w * CASH_BUFFER - current_value) / price)
        if qty <= 0:
            return ZERO, "importo inferiore al prezzo di un'azione"
    else:
        qty = min(floor_qty((current_value - total * w) / price), free) if w > ZERO else free
        if qty <= 0:
            return ZERO, "nessuna azione da vendere"
    rebalance = held > ZERO and (action == "buy" or w > ZERO)
    if rebalance and qty * price < min_order:
        return ZERO, f"ribilanciamento di {qty * price:.0f} € sotto l'ordine minimo di {min_order:.0f} €"
    return qty, None
