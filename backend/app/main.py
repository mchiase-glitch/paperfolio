import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, scheduler
from .api import auto_portfolio as auto_api
from .api import backtest as backtest_api
from .api import events, fiscal, instruments, orders, portfolio, settings, watchlist
from .api.common import DecimalJSONResponse
from .database import SessionLocal, engine
from .migrate import upgrade_to_head
from .services import auto_portfolio as auto_svc
from .services import backtest as backtest_svc
from .services import portfolio as portfolio_svc
from .services.settings import seed_defaults
from .services.universes import seed_universes

logging.basicConfig(level=logging.INFO)


def _run_recovery() -> None:
    with SessionLocal() as db:
        auto_svc.recovery_run(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.begin() as conn:
        upgrade_to_head(conn)
    with SessionLocal() as db:
        seed_defaults(db)
        seed_universes(db)
        portfolio_svc.active_account(db)
        portfolio_svc.charge_past_years(db)
    sched = scheduler.start() if config.ENABLE_SCHEDULER else None
    if sched:
        sched.add_job(scheduler.run_daily_snapshot, id="startup_snapshot")
        sched.add_job(scheduler.run_corporate_events, id="startup_events")
        sched.add_job(_run_recovery, id="startup_recovery")
    backtest_svc.start_worker()  # riprende i backtest interrotti da un riavvio
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="PaperFolio", default_response_class=DecimalJSONResponse, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

for module in (portfolio, instruments, orders, fiscal, settings, events, watchlist, auto_api, backtest_api):
    app.include_router(module.router)


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """I file dell'interfaccia vanno sempre ricontrollati (risposta 304 se invariati):
    dopo un deploy il telefono non deve mescolare file vecchi e nuovi."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
