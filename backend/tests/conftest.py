import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

os.environ["ENABLE_SCHEDULER"] = "0"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/api_test.db"

import pytest
from sqlalchemy.orm import sessionmaker

from app.data_provider import CorporateActions, Quote, set_provider
from app.database import make_engine
from app.migrate import upgrade_to_head
from app.models import Instrument
from app.services import portfolio
from app.services.settings import seed_defaults

D = Decimal


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# Mercoledì 12/03/2025: Borsa Italiana aperta 09:00-17:30 Roma (08:00-16:30 UTC), NYSE 13:30-20:00 UTC
OPEN_MIL = utc(2025, 3, 12, 10, 0)
OPEN_NYSE = utc(2025, 3, 12, 15, 0)
SATURDAY = utc(2025, 3, 15, 10, 0)


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.quotes: dict[str, Quote] = {}
        self.fx: dict[str, Decimal] = {"USD": D("1.08")}
        self.actions: dict[str, CorporateActions] = {}

    def set(self, symbol, price, when, currency="EUR", prev_close=None):
        self.quotes[symbol] = Quote(D(price), currency, when, None if prev_close is None else D(prev_close))

    def quote(self, symbol):
        return self.quotes[symbol]

    def fx_rate(self, currency):
        return Quote(self.fx[currency], currency, OPEN_MIL)

    def search(self, query):
        return []

    def info(self, symbol):
        raise NotImplementedError

    def history(self, symbol, period):
        return []

    def corporate_actions(self, symbol):
        return self.actions.get(symbol, CorporateActions([], [], []))


@pytest.fixture
def provider():
    p = FakeProvider()
    set_provider(p)
    return p


@pytest.fixture
def db(tmp_path, provider):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        upgrade_to_head(conn)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def account(db):
    return portfolio.open_account(db, D("10000"), now=utc(2025, 1, 2, 9, 0))


def add_stock(db, symbol="ENI.MI", country="IT", market="ITA", exchange="XMIL", currency="EUR",
              fiscal_category="azioni", type="stock") -> Instrument:
    inst = Instrument(symbol=symbol, name=symbol, type=type, market=market, exchange=exchange, currency=currency,
                      country=country, fiscal_category=fiscal_category, data_source="yfinance")
    db.add(inst)
    db.commit()
    return inst
