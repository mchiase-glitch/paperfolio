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
# Fase E2 (+1 a tutte): limiti per titolo (10%, P5 20%) e per settore (30%) predefiniti, dimensionamento e stop.
STRATEGY_VERSIONS: dict[str, str] = {
    "P1": "2",
    "P2": "3",
    "P3": "2",
    "P4": "2",
    "P5": "2",
    "P6": "2",
    "P7": "2",
}
