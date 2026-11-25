from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSetting, CommissionRule, TaxRule, WithholdingRate

INSTRUMENT_TYPES = ["stock", "etf", "bond", "derivative"]

DEFAULT_COMMISSIONS = {
    "ITA": ("3.00", "0.0007", "5.00"),
    "EUR": ("12.00", "0.0007", "5.00"),
    "USA": ("6.00", "0.0007", "5.00"),
}

DEFAULT_TAX_RULES = [
    # categoria, etichetta, aliquota, base imponibile, tipo plus, tipo minus
    ("azioni", "Azioni", "0.26", "1", "diversi", "diversi"),
    ("etf_armonizzati", "ETF armonizzati", "0.26", "1", "capitale", "diversi"),
    ("obbligazioni_societarie", "Obbligazioni societarie", "0.26", "1", "diversi", "diversi"),
    ("titoli_stato_whitelist", "Titoli di Stato white list", "0.26", "0.4808", "diversi", "diversi"),
    ("derivati", "Derivati", "0.26", "1", "diversi", "diversi"),
]

# Ritenuta alla fonte trattenuta dal paese emittente prima dell'accredito (senza pratiche di rimborso).
# Modificabili in Impostazioni.
DEFAULT_WITHHOLDING = {
    "US": "0.15",      # con il modulo W-8BEN
    "FR": "0.128",     # persone fisiche non residenti
    "DE": "0.26375",   # 25% + contributo di solidarietà
    "ES": "0.19",
    "NL": "0.15",
    "BE": "0.30",
    "FI": "0.35",
}

DEFAULT_SETTINGS = {
    "fx_spread": "0.001",
    "reservation_margin": "0.05",
    "tobin_rate": "0.001",
    "stamp_duty_rate": "0.002",
    "allow_short_selling": "0",
}


def seed_defaults(db: Session) -> None:
    """Inserisce i valori iniziali mancanti, senza toccare quelli già modificati."""
    existing_comm = {(r.instrument_type, r.market) for r in db.scalars(select(CommissionRule))}
    for itype in INSTRUMENT_TYPES:
        for market, (fixed, pct, minimum) in DEFAULT_COMMISSIONS.items():
            if (itype, market) not in existing_comm:
                db.add(CommissionRule(instrument_type=itype, market=market, fixed_eur=Decimal(fixed),
                                      pct=Decimal(pct), minimum_eur=Decimal(minimum)))
    existing_tax = set(db.scalars(select(TaxRule.fiscal_category)))
    for cat, label, rate, base, gains, losses in DEFAULT_TAX_RULES:
        if cat not in existing_tax:
            db.add(TaxRule(fiscal_category=cat, label=label, rate=Decimal(rate), base_factor=Decimal(base),
                           gains_kind=gains, losses_kind=losses))
    existing_wh = set(db.scalars(select(WithholdingRate.country)))
    for country, rate in DEFAULT_WITHHOLDING.items():
        if country not in existing_wh:
            db.add(WithholdingRate(country=country, rate=Decimal(rate)))
    existing_set = set(db.scalars(select(AppSetting.key)))
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing_set:
            db.add(AppSetting(key=key, value=value))
    db.commit()


def get_decimal(db: Session, key: str) -> Decimal:
    row = db.get(AppSetting, key)
    return Decimal(row.value if row else DEFAULT_SETTINGS[key])


def get_bool(db: Session, key: str) -> bool:
    row = db.get(AppSetting, key)
    return (row.value if row else DEFAULT_SETTINGS[key]) == "1"


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
