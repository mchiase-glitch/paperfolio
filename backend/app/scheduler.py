import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from . import config
from .database import SessionLocal
from .models import Account
from .services import orders, portfolio

log = logging.getLogger("paperfolio.scheduler")


def run_pending_orders() -> None:
    with SessionLocal() as db:
        done = orders.process_pending(db)
        if done:
            log.info("Ordini in attesa elaborati: %s", [(o.id, o.status) for o in done])
            for account_id in {o.account_id for o in done}:
                portfolio.snapshot(db, db.get(Account, account_id))


def run_daily_snapshot() -> None:
    with SessionLocal() as db:
        for account in db.scalars(select(Account).where(Account.closed_at.is_(None))):
            portfolio.snapshot(db, account)


def run_stamp_duty() -> None:
    with SessionLocal() as db:
        portfolio.charge_past_years(db)


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=config.DISPLAY_TZ)
    sched.add_job(run_pending_orders, "interval", seconds=60, id="pending_orders", max_instances=1, coalesce=True)
    sched.add_job(run_daily_snapshot, "cron", hour=23, minute=0, id="daily_snapshot")
    sched.add_job(run_stamp_duty, "cron", month=1, day=1, hour=0, minute=10, id="stamp_duty")
    sched.start()
    return sched
