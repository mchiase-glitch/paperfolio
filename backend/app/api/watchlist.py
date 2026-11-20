from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Instrument, WatchlistItem
from ..services import prices

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def list_watchlist(db: Session = Depends(get_db)):
    out = []
    for item in db.scalars(select(WatchlistItem).order_by(WatchlistItem.added_at)):
        inst = db.get(Instrument, item.instrument_id)
        row = {"instrument_id": inst.id, "symbol": inst.symbol, "name": inst.name, "type": inst.type,
               "market": inst.market, "currency": inst.currency, "price": None, "change_pct": None,
               "price_time": None, "is_manual": inst.data_source == "manual", "error": None}
        try:
            p = prices.get_price(db, inst)
            row.update(price=p.price, price_time=p.price_time, stale=p.stale,
                       change_pct=(p.price / p.prev_close - 1) * 100 if p.prev_close else None)
        except Exception as exc:
            row["error"] = str(exc)
        out.append(row)
    return {"items": out}


def _instrument(db: Session, instrument_id: int) -> Instrument:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(404, "Strumento non trovato")
    return inst


@router.post("/{instrument_id}")
def add(instrument_id: int, db: Session = Depends(get_db)):
    _instrument(db, instrument_id)
    if db.get(WatchlistItem, instrument_id) is None:
        db.add(WatchlistItem(instrument_id=instrument_id))
        db.commit()
    return {"watched": True}


@router.delete("/{instrument_id}")
def remove(instrument_id: int, db: Session = Depends(get_db)):
    item = db.get(WatchlistItem, instrument_id)
    if item is not None:
        db.delete(item)
        db.commit()
    return {"watched": False}
