from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, DecimalText, UTCDateTime, utcnow


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    initial_capital: Mapped[Decimal] = mapped_column(DecimalText)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    strategy_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FK → strategy_configs


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), unique=True)  # simbolo per la fonte dati
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))  # stock / etf / bond / derivative
    market: Mapped[str] = mapped_column(String(3))  # ITA / EUR / USA
    exchange: Mapped[str] = mapped_column(String(10))  # codice MIC del calendario (XMIL, XNYS, ...)
    currency: Mapped[str] = mapped_column(String(3))
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)  # paese emittente ISO-2
    fiscal_category: Mapped[str] = mapped_column(String(40))
    data_source: Mapped[str] = mapped_column(String(20), default="yfinance")  # yfinance / manual

    # Predisposizione derivati (fase 5)
    multiplier: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("1"))
    underlying_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), nullable=True)
    strike: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(4), nullable=True)  # call / put

    # Predisposizione obbligazioni (fase 3)
    coupon_rate: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    coupon_frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maturity: Mapped[date | None] = mapped_column(Date, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # inizio maturazione della prima cedola
    lot_size: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # taglio minimo del nominale
    day_count: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ACT/ACT oppure 30/360

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LedgerEntry(Base):
    """Registro append-only: ogni movimento del conto. Mai modificato o cancellato (trigger SQL)."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    # deposit, buy, sell, capital_gain_tax, stamp_duty, dividend, coupon, redemption, split,
    # margin_call, daily_settlement
    kind: Mapped[str] = mapped_column(String(30))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    position_side: Mapped[str] = mapped_column(String(5), default="long")  # long / short

    quantity: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # valuta strumento
    price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    accrued_interest: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)

    fx_market: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # unità valuta per 1 EUR
    fx_spread: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    fx_applied: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)

    gross_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # controvalore
    commission_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    tobin_tax_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    tax_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    cash_delta_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))

    # Solo vendite: esito fiscale calcolato all'esecuzione
    realized_gross_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    realized_fiscal_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    taxable_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    loss_added_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # entra nello zainetto
    loss_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    fiscal_category: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Predisposizione derivati: margini e liquidazione giornaliera
    margin_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)

    tax_year: Mapped[int | None] = mapped_column(Integer, nullable=True)  # per bollo
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Eventi societari
    corporate_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    withholding_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # ritenuta estera
    ratio: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # split

    # Obbligazioni: il rateo si calcola alla data di regolamento (T+2), che decide anche il diritto alla cedola
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accrued_interest_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # rateo lordo
    interest_tax_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # < 0 = credito d'imposta


class CorporateEvent(Base):
    """Fatto societario relativo allo strumento (non al conto). Gli effetti sul conto vanno nel ledger."""

    __tablename__ = "corporate_events"
    __table_args__ = (UniqueConstraint("instrument_id", "kind", "ex_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # dividend / split / coupon / redemption
    ex_date: Mapped[date] = mapped_column(Date)  # stacco o efficacia dello split
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_date_estimated: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # per azione, valuta strumento
    ratio: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # yfinance / manual
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LossUsage(Base):
    """Utilizzo di una minus dello zainetto a compensazione di una plus. Append-only."""

    __tablename__ = "loss_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    loss_entry_id: Mapped[int] = mapped_column(ForeignKey("ledger_entries.id"))
    used_by_entry_id: Mapped[int] = mapped_column(ForeignKey("ledger_entries.id"))
    amount_eur: Mapped[Decimal] = mapped_column(DecimalText)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(4))  # buy / sell
    position_side: Mapped[str] = mapped_column(String(5), default="long")
    order_type: Mapped[str] = mapped_column(String(14), default="market")  # market / limit / stop / trailing_stop
    trigger_price: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # limite o soglia di stop
    trailing_distance: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # distanza trailing stop (%)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # ultimo giorno di validità (ora di Roma)
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    status: Mapped[str] = mapped_column(String(10), index=True)  # pending / executed / cancelled / rejected / expired
    reserved_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class WatchlistItem(Base):
    """Titoli seguiti senza posizione (comuni a tutti i portafogli)."""

    __tablename__ = "watchlist"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Price(Base):
    """Ultimo prezzo noto per strumento (cache, non storico)."""

    __tablename__ = "prices"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(DecimalText)
    prev_close: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    price_time: Mapped[datetime] = mapped_column(UTCDateTime)  # orario dell'ultimo prezzo
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(20))
    is_manual: Mapped[int] = mapped_column(Integer, default=0)


class FxRate(Base):
    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)  # unità per 1 EUR
    rate: Mapped[Decimal] = mapped_column(DecimalText)
    rate_time: Mapped[datetime] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DailyValuation(Base):
    """Controvalore di mercato degli strumenti a fine giornata, base del bollo pro rata."""

    __tablename__ = "daily_valuations"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    positions_value_eur: Mapped[Decimal] = mapped_column(DecimalText)


class CommissionRule(Base):
    __tablename__ = "commission_rules"
    __table_args__ = (UniqueConstraint("instrument_type", "market"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_type: Mapped[str] = mapped_column(String(20))
    market: Mapped[str] = mapped_column(String(3))
    fixed_eur: Mapped[Decimal] = mapped_column(DecimalText)
    pct: Mapped[Decimal] = mapped_column(DecimalText)
    minimum_eur: Mapped[Decimal] = mapped_column(DecimalText)


class TaxRule(Base):
    __tablename__ = "tax_rules"

    fiscal_category: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    rate: Mapped[Decimal] = mapped_column(DecimalText)
    base_factor: Mapped[Decimal] = mapped_column(DecimalText)  # 1 oppure 0.4808 per white list
    gains_kind: Mapped[str] = mapped_column(String(10))  # diversi (compensabili) / capitale
    losses_kind: Mapped[str] = mapped_column(String(10))  # diversi (zainetto) / none


class WithholdingRate(Base):
    __tablename__ = "withholding_rates"

    country: Mapped[str] = mapped_column(String(2), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(DecimalText)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


# ── Portafogli automatici (fase A) ───────────────────────────────────────────

class UniverseList(Base):
    """Lista di titoli ammessi per una strategia (FTSE MIB, Euro Stoxx 50, S&P 100, personalizzata)."""

    __tablename__ = "universe_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)   # 'ftse_mib' | 'eurostoxx50' | 'sp100' | custom
    label: Mapped[str] = mapped_column(String(100))              # etichetta leggibile
    source: Mapped[str] = mapped_column(String(20))              # 'seed' | 'wikipedia' | 'manual'
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class UniverseListItem(Base):
    __tablename__ = "universe_list_items"
    __table_args__ = (UniqueConstraint("list_id", "symbol", name="uq_list_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("universe_lists.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40))
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)


class StrategyConfig(Base):
    """Configurazione di un portafoglio automatico (tipo di strategia + parametri)."""

    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    strategy_type: Mapped[str] = mapped_column(String(10))   # P1 … P7
    params_json: Mapped[str] = mapped_column(Text)            # JSON con tutti i parametri
    is_paused: Mapped[int] = mapped_column(Integer, default=0)
    is_drawdown_braking: Mapped[int] = mapped_column(Integer, default=0)  # freno drawdown attivo
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class StrategyRun(Base):
    """Ogni esecuzione (o tentativo) di una strategia. run_key garantisce l'idempotenza."""

    __tablename__ = "strategy_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_config_id: Mapped[int] = mapped_column(ForeignKey("strategy_configs.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    run_key: Mapped[str] = mapped_column(String(100), unique=True)
    ran_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    is_dry_run: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10))   # ok / skipped / error
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class StrategyDecision(Base):
    """Registro di ogni decisione presa dalla strategia, con spiegazione in italiano."""

    __tablename__ = "strategy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("strategy_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(10))     # buy / sell / hold / skip
    reason_it: Mapped[str] = mapped_column(Text)
    signal_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PriceHistoryCache(Base):
    """OHLCV giornaliero non rettificato (dividendi e split a parte) per il backtest e gli indicatori."""

    __tablename__ = "price_history_cache"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_price_history_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    high: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    low: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    close: Mapped[float] = mapped_column(sa.Float)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dividend: Mapped[float] = mapped_column(sa.Float, default=0.0)
    split_ratio: Mapped[float] = mapped_column(sa.Float, default=1.0)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
