from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CorporateEvent, Instrument, LedgerEntry
from ..services import corporate_events, portfolio

router = APIRouter(prefix="/api", tags=["eventi societari"])


def event_dict(db: Session, ev: CorporateEvent, account_id: int) -> dict:
    credited = db.scalar(select(LedgerEntry).where(LedgerEntry.account_id == account_id,
                                                   LedgerEntry.corporate_event_id == ev.id,
                                                   LedgerEntry.kind == ev.kind))
    return {
        "id": ev.id, "kind": ev.kind, "ex_date": ev.ex_date, "pay_date": ev.pay_date,
        "pay_date_estimated": bool(ev.pay_date_estimated), "amount": ev.amount, "ratio": ev.ratio,
        "label": corporate_events.split_label(ev.ratio) if ev.kind == "split" else None,
        "source": ev.source, "processed": credited is not None,
        "net_eur": credited.cash_delta_eur if credited is not None and ev.kind == "dividend" else None,
        "editable": not corporate_events._processed_anywhere(db, ev),
    }


@router.get("/instruments/{instrument_id}/events")
def list_events(instrument_id: int, db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    q = select(CorporateEvent).where(CorporateEvent.instrument_id == instrument_id).order_by(CorporateEvent.ex_date.desc())
    return {"events": [event_dict(db, ev, account.id) for ev in db.scalars(q)]}


class EventIn(BaseModel):
    kind: Literal["dividend", "split"]
    ex_date: date
    pay_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    ratio: Decimal | None = Field(default=None, gt=0)


@router.post("/instruments/{instrument_id}/events")
def add_event(instrument_id: int, body: EventIn, db: Session = Depends(get_db)):
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(404, "Strumento non trovato")
    if body.kind == "dividend":
        if body.amount is None:
            raise HTTPException(400, "Indica l'importo per azione")
        if body.pay_date and body.pay_date < body.ex_date:
            raise HTTPException(400, "Il pagamento non può precedere lo stacco")
        ev = CorporateEvent(instrument_id=inst.id, kind="dividend", ex_date=body.ex_date, amount=body.amount,
                            pay_date=body.pay_date or corporate_events.estimate_pay_date(inst, body.ex_date),
                            pay_date_estimated=0 if body.pay_date else 1, source="manual")
    else:
        if body.ratio is None or body.ratio == 1:
            raise HTTPException(400, "Indica il rapporto (es. 2 per 2×1, 0.1 per 1×10)")
        ev = CorporateEvent(instrument_id=inst.id, kind="split", ex_date=body.ex_date, ratio=body.ratio, source="manual")
    db.add(ev)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Esiste già un evento dello stesso tipo in quella data")
    corporate_events.process(db)
    return event_dict(db, ev, portfolio.active_account(db).id)


class EventUpdate(BaseModel):
    pay_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)


@router.put("/events/{event_id}")
def update_event(event_id: int, body: EventUpdate, db: Session = Depends(get_db)):
    ev = db.get(CorporateEvent, event_id)
    if ev is None:
        raise HTTPException(404, "Evento non trovato")
    if corporate_events._processed_anywhere(db, ev):
        raise HTTPException(400, "Evento già registrato nel conto: non è più modificabile")
    if ev.kind != "dividend":
        raise HTTPException(400, "Si possono correggere solo data di pagamento e importo dei dividendi")
    if body.pay_date is not None:
        if body.pay_date < ev.ex_date:
            raise HTTPException(400, "Il pagamento non può precedere lo stacco")
        ev.pay_date, ev.pay_date_estimated = body.pay_date, 0
    if body.amount is not None:
        ev.amount = body.amount
    db.commit()
    corporate_events.process(db)
    return event_dict(db, ev, portfolio.active_account(db).id)
