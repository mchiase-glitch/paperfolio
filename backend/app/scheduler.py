import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from . import config
from .database import SessionLocal
from .models import Account
from .services import auto_portfolio, corporate_events, orders, portfolio

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


def run_corporate_events() -> None:
    with SessionLocal() as db:
        corporate_events.sync_all(db)
        done = corporate_events.process(db)
        if done:
            log.info("Eventi societari elaborati: %s", done)


def run_stamp_duty() -> None:
    with SessionLocal() as db:
        portfolio.charge_past_years(db)


def run_auto_strategies(region: str) -> None:
    """Poco prima della chiusura del mercato: gli ordini si eseguono subito al prezzo corrente."""
    with SessionLocal() as db:
        results = auto_portfolio.run_all_strategies(db, region=region)
        if results:
            log.info("Strategie automatiche %s: %s", region, results)


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=config.DISPLAY_TZ)
    sched.add_job(run_pending_orders, "interval", seconds=60, id="pending_orders", max_instances=1, coalesce=True)
    sched.add_job(run_daily_snapshot, "cron", hour=23, minute=0, id="daily_snapshot")
    sched.add_job(run_stamp_duty, "cron", month=1, day=1, hour=0, minute=10, id="stamp_duty")
    sched.add_job(run_corporate_events, "cron", hour=7, minute=0, id="corporate_events")
    # Strategie automatiche: mezz'ora prima della chiusura di Borsa Italiana/Xetra (17:30) e NYSE (22:00)
    for region, (hour, minute) in auto_portfolio.SCHEDULE.items():
        sched.add_job(run_auto_strategies, "cron", args=[region], day_of_week="mon-fri", hour=hour, minute=minute,
                      id=f"auto_{region.lower()}", max_instances=1, coalesce=True)
    sched.start()
    return sched
