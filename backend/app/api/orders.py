import csv
import io
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data_provider import DataProviderError
from ..database import get_db
from ..models import Instrument, LedgerEntry, Order
from ..services import orders, portfolio

router = APIRouter(prefix="/api", tags=["ordini"])

KIND_LABELS = {
    "deposit": "Versamento", "buy": "Acquisto", "sell": "Vendita", "stamp_duty": "Imposta di bollo",
    "dividend": "Dividendo", "coupon": "Cedola", "redemption": "Rimborso a scadenza", "split": "Frazionamento",
}


class OrderRequest(BaseModel):
    instrument_id: int
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    order_type: Literal["market", "limit", "stop"] = "market"
    trigger_price: Decimal | None = Field(default=None, gt=0)
    expires_on: date | None = None


def _instrument(db: Session, instrument_id: int) -> Instrument:
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(404, "Strumento non trovato")
    return inst


@router.post("/orders/preview")
def preview(body: OrderRequest, db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    try:
        pv = orders.preview(db, account, _instrument(db, body.instrument_id), body.side, body.quantity,
                            order_type=body.order_type, trigger_price=body.trigger_price)
    except (orders.OrderError, DataProviderError) as exc:
        raise HTTPException(400, str(exc))
    return pv.public()


@router.post("/orders")
def place(body: OrderRequest, db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    try:
        order = orders.place_order(db, account, _instrument(db, body.instrument_id), body.side, body.quantity,
                                   order_type=body.order_type, trigger_price=body.trigger_price,
                                   expires_on=body.expires_on)
    except (orders.OrderError, DataProviderError) as exc:
        raise HTTPException(400, str(exc))
    if order.status == "executed":
        portfolio.snapshot(db, account)
    return order_dict(db, order)


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Ordine non trovato")
    try:
        orders.cancel_order(db, order)
    except orders.OrderError as exc:
        raise HTTPException(400, str(exc))
    return order_dict(db, order)


@router.get("/orders")
def list_orders(db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    q = select(Order).where(Order.account_id == account.id).order_by(Order.created_at.desc())
    return {"orders": [order_dict(db, o) for o in db.scalars(q)]}


@router.get("/movements")
def movements(db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    return {"movements": [entry_dict(db, e) for e in _entries(db, account.id)]}


@router.get("/movements.csv")
def movements_csv(db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    cols = ["data_ora_roma", "tipo", "simbolo", "isin", "strumento", "quantita", "prezzo", "valuta",
            "cambio_mercato", "cambio_applicato", "controvalore_eur", "commissione_eur", "tobin_tax_eur",
            "rateo_eur", "imposta_rateo_eur", "data_regolamento",
            "ritenuta_estera_eur", "imposte_eur", "plus_minus_fiscale_eur", "importo_netto_eur", "descrizione"]
    w.writerow(cols)

    def it(v):  # formato numerico italiano per Excel
        return "" if v is None else str(v).replace(".", ",")

    for e in _entries(db, account.id):
        d = entry_dict(db, e)
        w.writerow([e.ts.astimezone(portfolio.ROME).strftime("%d/%m/%Y %H:%M:%S"), d["label"], d["symbol"] or "",
                    d["isin"] or "", d["name"] or "", it(e.quantity), it(e.price), e.price_currency or "",
                    it(e.fx_market), it(e.fx_applied), it(e.gross_eur), it(e.commission_eur), it(e.tobin_tax_eur),
                    it(e.accrued_interest_eur), it(e.interest_tax_eur),
                    e.settlement_date.strftime("%d/%m/%Y") if e.settlement_date else "",
                    it(e.withholding_eur), it(e.tax_eur), it(e.realized_fiscal_eur), it(e.cash_delta_eur),
                    e.description or ""])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="paperfolio_movimenti.csv"'})


def _entries(db: Session, account_id: int):
    q = select(LedgerEntry).where(LedgerEntry.account_id == account_id).order_by(LedgerEntry.ts.desc(),
                                                                               LedgerEntry.id.desc())
    return list(db.scalars(q))


def order_dict(db: Session, o: Order) -> dict:
    inst = db.get(Instrument, o.instrument_id)
    entry = db.scalar(select(LedgerEntry).where(LedgerEntry.order_id == o.id))
    return {
        "id": o.id, "instrument_id": o.instrument_id, "symbol": inst.symbol, "name": inst.name,
        "instrument_type": inst.type, "currency": inst.currency,
        "order_type": o.order_type, "trigger_price": o.trigger_price, "expires_on": o.expires_on,
        "side": o.side, "quantity": o.quantity, "status": o.status, "reserved_eur": o.reserved_eur,
        "created_at": o.created_at, "executed_at": o.executed_at, "cancelled_at": o.cancelled_at, "note": o.note,
        "execution": entry_dict(db, entry) if entry else None,
    }


def entry_dict(db: Session, e: LedgerEntry) -> dict:
    inst = db.get(Instrument, e.instrument_id) if e.instrument_id else None
    label = KIND_LABELS.get(e.kind, e.kind)
    if e.kind == "dividend" and inst and inst.type == "etf":
        label = "Distribuzione"
    return {
        "id": e.id, "ts": e.ts, "kind": e.kind, "label": label,
        "instrument_id": e.instrument_id, "symbol": inst.symbol if inst else None,
        "isin": inst.isin if inst else None, "name": inst.name if inst else None,
        "quantity": e.quantity, "price": e.price, "price_currency": e.price_currency,
        "fx_market": e.fx_market, "fx_applied": e.fx_applied, "gross_eur": e.gross_eur,
        "commission_eur": e.commission_eur, "tobin_tax_eur": e.tobin_tax_eur, "tax_eur": e.tax_eur,
        "realized_gross_eur": e.realized_gross_eur, "realized_fiscal_eur": e.realized_fiscal_eur,
        "loss_added_eur": e.loss_added_eur, "cash_delta_eur": e.cash_delta_eur, "description": e.description,
        "withholding_eur": e.withholding_eur, "ratio": e.ratio, "instrument_type": inst.type if inst else None,
        "accrued_interest": e.accrued_interest, "accrued_interest_eur": e.accrued_interest_eur,
        "interest_tax_eur": e.interest_tax_eur, "settlement_date": e.settlement_date,
    }
