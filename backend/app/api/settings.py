from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppSetting, CommissionRule, TaxRule, WithholdingRate
from ..services import portfolio
from ..services import settings as svc

router = APIRouter(prefix="/api/settings", tags=["impostazioni"])

NonNeg = Field(ge=0)


class CommissionIn(BaseModel):
    id: int
    fixed_eur: Decimal = NonNeg
    pct: Decimal = NonNeg
    minimum_eur: Decimal = NonNeg


class TaxRuleIn(BaseModel):
    fiscal_category: str
    rate: Decimal = Field(ge=0, le=1)
    base_factor: Decimal = Field(ge=0, le=1)


class WithholdingIn(BaseModel):
    country: str = Field(min_length=2, max_length=2)
    rate: Decimal = Field(ge=0, le=1)


class SettingsIn(BaseModel):
    commissions: list[CommissionIn] | None = None
    tax_rules: list[TaxRuleIn] | None = None
    withholding: list[WithholdingIn] | None = None
    fx_spread: Decimal | None = Field(default=None, ge=0, le=Decimal("0.1"))
    reservation_margin: Decimal | None = Field(default=None, ge=0, le=1)
    tobin_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.1"))
    stamp_duty_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.1"))


def _dump(db: Session) -> dict:
    account = portfolio.active_account(db)
    return {
        "initial_capital": account.initial_capital,
        "account_created_at": account.created_at,
        "commissions": [{"id": r.id, "instrument_type": r.instrument_type, "market": r.market,
                         "fixed_eur": r.fixed_eur, "pct": r.pct, "minimum_eur": r.minimum_eur}
                        for r in db.scalars(select(CommissionRule).order_by(CommissionRule.id))],
        "tax_rules": [{"fiscal_category": r.fiscal_category, "label": r.label, "rate": r.rate,
                       "base_factor": r.base_factor, "gains_kind": r.gains_kind, "losses_kind": r.losses_kind}
                      for r in db.scalars(select(TaxRule))],
        "withholding": [{"country": r.country, "rate": r.rate}
                        for r in db.scalars(select(WithholdingRate).order_by(WithholdingRate.country))],
        **{s.key: s.value for s in db.scalars(select(AppSetting))},
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return _dump(db)


@router.put("")
def update_settings(body: SettingsIn, db: Session = Depends(get_db)):
    for c in body.commissions or []:
        rule = db.get(CommissionRule, c.id)
        if rule is None:
            raise HTTPException(404, f"Regola commissione {c.id} non trovata")
        rule.fixed_eur, rule.pct, rule.minimum_eur = c.fixed_eur, c.pct, c.minimum_eur
    for t in body.tax_rules or []:
        rule = db.get(TaxRule, t.fiscal_category)
        if rule is None:
            raise HTTPException(404, f"Categoria fiscale {t.fiscal_category} non trovata")
        rule.rate, rule.base_factor = t.rate, t.base_factor
    for w in body.withholding or []:
        row = db.get(WithholdingRate, w.country.upper())
        if row:
            row.rate = w.rate
        else:
            db.add(WithholdingRate(country=w.country.upper(), rate=w.rate))
    for key in ("fx_spread", "reservation_margin", "tobin_rate", "stamp_duty_rate"):
        value = getattr(body, key)
        if value is not None:
            svc.set_value(db, key, str(value))
    db.commit()
    return _dump(db)


class ResetIn(BaseModel):
    capital: Decimal = Field(gt=0)
    confirm: bool


@router.post("/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(400, "Conferma richiesta")
    account = portfolio.reset(db, body.capital)
    return {"account_id": account.id, "initial_capital": account.initial_capital}
