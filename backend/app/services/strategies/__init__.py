from .base import BaseStrategy
from .p1_buy_hold import P1BuyHold
from .p2_trend import P2Trend

# Mappa tipo → classe strategia (dal vivo e nel backtest)
STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "P1": P1BuyHold,
    "P2": P2Trend,
}

# Versione delle regole di ogni strategia, salvata con ogni backtest: se le regole cambiano,
# i risultati vecchi restano riconoscibili. P2 v2: prezzi non più rettificati due volte per gli split.
STRATEGY_VERSIONS: dict[str, str] = {
    "P1": "1",
    "P2": "2",
}
