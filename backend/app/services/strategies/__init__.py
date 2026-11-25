from .base import BaseStrategy
from .p1_buy_hold import P1BuyHold
from .p2_trend import P2Trend
from .p3_dual_momentum import P3DualMomentum
from .p4_momentum import P4Momentum
from .p5_rsi2 import P5Rsi2
from .p6_value_quality import P6ValueQuality
from .p7_combined import P7Combined

# Mappa tipo → classe strategia (dal vivo e nel backtest)
STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "P1": P1BuyHold,
    "P2": P2Trend,
    "P3": P3DualMomentum,
    "P4": P4Momentum,
    "P5": P5Rsi2,
    "P6": P6ValueQuality,
    "P7": P7Combined,
}

# Versione delle regole di ogni strategia, salvata con ogni backtest: se le regole cambiano,
# i risultati vecchi restano riconoscibili. P2 v2: prezzi non più rettificati due volte per gli split.
STRATEGY_VERSIONS: dict[str, str] = {
    "P1": "1",
    "P2": "2",
    "P3": "1",
    "P4": "1",
    "P5": "1",
    "P6": "1",
    "P7": "1",
}
