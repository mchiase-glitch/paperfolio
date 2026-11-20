import time
from bisect import bisect_right
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..data_provider import get_provider
from ..database import get_db
from ..models import Account
from ..services import portfolio, positions
from ..services.money import eur

router = APIRouter(prefix="/api", tags=["portafoglio"])

# Indici di confronto (rendimento di prezzo, nella valuta dell'indice)
BENCHMARKS = {
    "FTSEMIB.MI": "FTSE MIB",
    "^STOXX50E": "Euro Stoxx 50",
    "SWDA.MI": "MSCI World (ETF in €)",
    "^GSPC": "S&P 500 (in $)",
}
_bench_cache: dict[tuple[str, str], tuple[float, list]] = {}


@router.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    return portfolio.summary(db, portfolio.active_account(db))


def _period(days: int) -> str:
    for limit, period in ((28, "1mo"), (85, "3mo"), (175, "6mo"), (360, "1y"), (725, "2y"), (1820, "5y")):
        if days <= limit:
            return period
    return "max"


def _benchmark(symbol: str, start: date, today: date) -> list[tuple[date, Decimal]]:
    period = _period((today - start).days + 7)
    key = (symbol, period)
    cached = _bench_cache.get(key)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    points = get_provider().history(symbol, period)
    _bench_cache[key] = (time.time(), points)
    return points


@router.get("/portfolio/history")
def history(benchmark: str = "FTSEMIB.MI", db: Session = Depends(get_db)):
    """Valore del portafoglio giorno per giorno e, in base 100, l'indice di confronto."""
    account = portfolio.active_account(db)
    points = portfolio.value_history(db, account)
    base = account.initial_capital
    out = [{"date": d, "value": v, "pct": (v / base - 1) * 100} for d, v in points]
    bench_error = None
    if benchmark not in BENCHMARKS:
        raise HTTPException(400, "Indice non disponibile")
    try:
        series = _benchmark(benchmark, points[0][0], points[-1][0])
        dates = [d for d, _ in series]
        start_idx = bisect_right(dates, points[0][0]) - 1
        start_close = series[max(start_idx, 0)][1] if series else None
        for item in out:
            idx = bisect_right(dates, item["date"]) - 1  # ultima chiusura disponibile in quella data
            item["bench_pct"] = (series[idx][1] / start_close - 1) * 100 if idx >= 0 and start_close else None
    except Exception as exc:
        bench_error = f"Indice non disponibile: {exc}"
    return {"points": out, "initial_capital": base, "benchmark": benchmark,
            "benchmarks": [{"symbol": s, "label": label} for s, label in BENCHMARKS.items()], "error": bench_error}


# --- Più portafogli -----------------------------------------------------------------

def _account_dict(db: Session, a: Account, current_id: int) -> dict:
    cash = positions.cash_balance(db, a.id)
    try:
        value = eur(cash + portfolio.positions_value(db, a))
    except Exception:
        value = None
    return {"id": a.id, "name": a.name, "initial_capital": a.initial_capital, "created_at": a.created_at,
            "cash": eur(cash), "total_value": value, "current": a.id == current_id}


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db)):
    current = portfolio.active_account(db)
    return {"current_id": current.id, "accounts": [_account_dict(db, a, current.id) for a in portfolio.open_accounts(db)]}


class NewAccount(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    capital: Decimal = Field(gt=0)


@router.post("/accounts")
def create_account(body: NewAccount, db: Session = Depends(get_db)):
    a = portfolio.open_account(db, body.capital, name=body.name.strip())
    return _account_dict(db, a, a.id)


def _open(db: Session, account_id: int) -> Account:
    a = db.get(Account, account_id)
    if a is None or a.closed_at is not None:
        raise HTTPException(404, "Portafoglio non trovato")
    return a


@router.post("/accounts/{account_id}/select")
def select(account_id: int, db: Session = Depends(get_db)):
    a = _open(db, account_id)
    portfolio.select_account(db, a)
    return _account_dict(db, a, a.id)


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.put("/accounts/{account_id}")
def rename(account_id: int, body: Rename, db: Session = Depends(get_db)):
    a = _open(db, account_id)
    a.name = body.name.strip()
    db.commit()
    return _account_dict(db, a, portfolio.active_account(db).id)


class Confirm(BaseModel):
    confirm: bool


@router.post("/accounts/{account_id}/close")
def close(account_id: int, body: Confirm, db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(400, "Conferma richiesta")
    a = _open(db, account_id)
    if len(portfolio.open_accounts(db)) < 2:
        raise HTTPException(400, "È l'unico portafoglio aperto: usa il reset per ripartire da zero")
    portfolio.close_account(db, a)
    return list_accounts(db)
