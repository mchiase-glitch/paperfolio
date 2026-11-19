from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..data_provider import DataProviderError, get_provider
from ..database import get_db, utcnow
from ..models import Instrument
from ..services import portfolio, positions, prices

router = APIRouter(prefix="/api/instruments", tags=["strumenti"])

FISCAL_BY_TYPE = {"stock": "azioni", "etf": "etf_armonizzati"}


def unsupported_reason(itype: str, market: str | None) -> str | None:
    if market is None:
        return "borsa non supportata"
    if itype == "etf" and market == "USA":
        # Gli ETF USA non sono UCITS e non sono acquistabili dai risparmiatori italiani
        return "ETF non armonizzato (USA)"
    if itype not in FISCAL_BY_TYPE:
        return "disponibile nelle prossime fasi"
    return None


def instrument_dict(inst: Instrument) -> dict:
    return {
        "id": inst.id, "symbol": inst.symbol, "isin": inst.isin, "name": inst.name, "type": inst.type,
        "market": inst.market, "exchange": inst.exchange, "currency": inst.currency, "country": inst.country,
        "fiscal_category": inst.fiscal_category, "data_source": inst.data_source,
    }


@router.get("/search")
def search(q: str, type: str | None = None, db: Session = Depends(get_db)):
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    like = f"%{q}%"
    local = db.scalars(select(Instrument).where(or_(Instrument.name.ilike(like), Instrument.symbol.ilike(like),
                                                    Instrument.isin.ilike(like))).limit(20))
    results, seen = [], set()
    for inst in local:
        if type and inst.type != type:
            continue
        seen.add(inst.symbol)
        results.append({**instrument_dict(inst), "known": True, "supported": True,
                        "exchange_label": inst.exchange})
    error = None
    try:
        for r in get_provider().search(q):
            if r.symbol in seen or (type and r.type != type):
                continue
            reason = unsupported_reason(r.type, r.market)
            results.append({"symbol": r.symbol, "name": r.name, "type": r.type, "market": r.market,
                            "exchange": r.exchange, "exchange_label": r.exchange_label, "known": False,
                            "supported": reason is None, "reason": reason})
    except DataProviderError as exc:
        error = str(exc)
    return {"results": results, "error": error}


class AddInstrument(BaseModel):
    symbol: str
    isin: str | None = None


@router.post("")
def add_instrument(body: AddInstrument, db: Session = Depends(get_db)):
    existing = db.scalar(select(Instrument).where(Instrument.symbol == body.symbol))
    if existing:
        return instrument_dict(existing)
    try:
        info = get_provider().info(body.symbol)
    except DataProviderError as exc:
        raise HTTPException(400, str(exc))
    reason = unsupported_reason(info.type, info.market)
    if reason:
        raise HTTPException(400, f"Strumento non negoziabile: {reason}")
    isin = (body.isin or info.isin or "").upper() or None
    # Senza paese dalla fonte (tipico degli ETF) si usa il prefisso dell'ISIN: IE, LU, ...
    country = info.country or (isin[:2] if isin else None)
    inst = Instrument(symbol=info.symbol, isin=isin, name=info.name, type=info.type,
                      market=info.market, exchange=info.exchange, currency=info.currency, country=country,
                      fiscal_category=FISCAL_BY_TYPE[info.type], data_source="yfinance")
    db.add(inst)
    db.commit()
    return instrument_dict(inst)


class ManualInstrument(BaseModel):
    name: str
    isin: str | None = None
    symbol: str
    type: Literal["stock", "etf"] = "stock"
    market: Literal["ITA", "EUR", "USA"]
    exchange: str = "XMIL"
    currency: str = "EUR"
    country: str | None = None
    price: Decimal = Field(gt=0)


@router.post("/manual")
def add_manual(body: ManualInstrument, db: Session = Depends(get_db)):
    if db.scalar(select(Instrument).where(Instrument.symbol == body.symbol)):
        raise HTTPException(400, "Simbolo già presente")
    inst = Instrument(symbol=body.symbol, isin=body.isin, name=body.name, type=body.type, market=body.market,
                      exchange=body.exchange, currency=body.currency.upper(), country=body.country,
                      fiscal_category=FISCAL_BY_TYPE[body.type], data_source="manual")
    db.add(inst)
    db.flush()
    prices.set_manual_price(db, inst, body.price, utcnow())
    return instrument_dict(inst)


class ManualPrice(BaseModel):
    price: Decimal = Field(gt=0)
    price_time: datetime | None = None


@router.put("/{instrument_id}/manual-price")
def manual_price(instrument_id: int, body: ManualPrice, db: Session = Depends(get_db)):
    inst = _get(db, instrument_id)
    if inst.data_source != "manual":
        raise HTTPException(400, "Lo strumento ha una quotazione automatica")
    prices.set_manual_price(db, inst, body.price, body.price_time or utcnow())
    return {"ok": True}


@router.get("/{instrument_id}")
def detail(instrument_id: int, db: Session = Depends(get_db)):
    inst = _get(db, instrument_id)
    account = portfolio.active_account(db)
    quote, error = None, None
    try:
        p = prices.get_price(db, inst)
        fx, fx_time = prices.get_fx(db, inst.currency)
        quote = {"price": p.price, "prev_close": p.prev_close, "currency": p.currency, "price_time": p.price_time,
                 "is_manual": p.is_manual, "stale": p.stale, "fx_market": fx, "fx_time": fx_time,
                 "change_pct": (p.price / p.prev_close - 1) * 100 if p.prev_close else None}
    except DataProviderError as exc:
        error = str(exc)
    pos = positions.position(db, account.id, inst.id)
    return {
        "instrument": instrument_dict(inst), "quote": quote, "error": error,
        "position": {"quantity": pos.quantity, "avg_price": pos.avg_price, "avg_cost_eur": pos.avg_cost_eur,
                     "cost_eur": pos.cost_fiscal_eur} if pos.quantity else None,
    }


@router.get("/{instrument_id}/history")
def history(instrument_id: int, period: Literal["1mo", "3mo", "6mo", "1y", "5y"] = "3mo",
            db: Session = Depends(get_db)):
    inst = _get(db, instrument_id)
    if inst.data_source == "manual":
        return {"points": []}
    try:
        points = get_provider().history(inst.symbol, period)
    except Exception:
        points = []
    return {"points": [{"date": d, "close": c} for d, c in points]}


def _get(db: Session, instrument_id: int) -> Instrument:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(404, "Strumento non trovato")
    return inst
