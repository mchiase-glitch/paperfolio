from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db, utcnow
from ..models import LedgerEntry, LossUsage, TaxRule
from ..services import portfolio, positions
from ..services.money import ZERO
from ..services.tax import loss_lots

router = APIRouter(prefix="/api/fiscal", tags=["fiscale"])


@router.get("")
def fiscal(year: int | None = None, db: Session = Depends(get_db)):
    account = portfolio.active_account(db)
    now = utcnow()
    today = portfolio.rome_date(now)
    year = year or today.year
    labels = {r.fiscal_category: r.label for r in db.scalars(select(TaxRule))}

    by_cat: dict[str, dict] = {}
    totals = {"gains": ZERO, "losses": ZERO, "taxable": ZERO, "tax": ZERO, "commissions": ZERO,
              "tobin": ZERO, "stamp": ZERO, "loss_used": ZERO}
    income = {"gross": ZERO, "withholding": ZERO, "tax": ZERO, "net": ZERO, "count": 0}
    entry_year = {}
    for e in positions.ledger(db, account.id):
        y = portfolio.rome_date(e.ts).year
        entry_year[e.id] = y
        if y != year:
            continue
        totals["commissions"] += e.commission_eur
        totals["tobin"] += e.tobin_tax_eur
        if e.kind == "stamp_duty":
            totals["stamp"] += e.tax_eur
        if e.kind == "dividend":
            income["gross"] += e.gross_eur
            income["withholding"] += e.withholding_eur or ZERO
            income["tax"] += e.tax_eur
            income["net"] += e.cash_delta_eur
            income["count"] += 1
        if e.kind == "sell":
            cat = by_cat.setdefault(e.fiscal_category, {"category": e.fiscal_category,
                                                        "label": labels.get(e.fiscal_category, e.fiscal_category),
                                                        "gains": ZERO, "losses": ZERO, "taxable": ZERO, "tax": ZERO})
            r = e.realized_fiscal_eur or ZERO
            if r >= 0:
                cat["gains"] += r
                totals["gains"] += r
            else:
                cat["losses"] += -r
                totals["losses"] += -r
            cat["taxable"] += e.taxable_eur or ZERO
            cat["tax"] += e.tax_eur
            totals["taxable"] += e.taxable_eur or ZERO
            totals["tax"] += e.tax_eur
    for u in db.scalars(select(LossUsage).where(LossUsage.account_id == account.id)):
        if entry_year.get(u.used_by_entry_id) == year:
            totals["loss_used"] += u.amount_eur

    lots = [{"entry_id": lot.entry_id, "origin": lot.origin, "expiry": lot.expiry, "remaining": lot.remaining,
             "category": labels.get(lot.fiscal_category, lot.fiscal_category),
             "expired": lot.expiry < today} for lot in loss_lots(db, account.id) if lot.remaining > 0]
    stamp_years = [{"year": e.tax_year, "amount": e.tax_eur, "ts": e.ts}
                   for e in db.scalars(select(LedgerEntry).where(LedgerEntry.account_id == account.id,
                                                                 LedgerEntry.kind == "stamp_duty"))]
    return {
        "year": year,
        "categories": list(by_cat.values()),
        "totals": totals,
        "capital_income": income,
        "zainetto": lots,
        "zainetto_available": sum((lot["remaining"] for lot in lots if not lot["expired"]), ZERO),
        "stamp_duty": {"estimate_current_year": portfolio.stamp_estimate(db, account, now),
                       "current_year": today.year, "charged": stamp_years},
        "years": sorted({portfolio.rome_date(account.created_at).year, today.year, year}),
    }
