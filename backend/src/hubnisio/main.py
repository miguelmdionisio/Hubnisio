"""HTTP API entrypoint: `uvicorn hubnisio.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hubnisio.core.auth import check_auth_config
from hubnisio.core.routes import router as core_router
from hubnisio.core.settings import get_settings
from hubnisio.finance.api import router as finance_router
from hubnisio.finance.budgets_api import router as budgets_router
from hubnisio.finance.insights_api import router as insights_router
from hubnisio.finance.investments_api import router as investments_router
from hubnisio.finance.organize_api import router as organize_router
from hubnisio.finance.recurring_api import router as recurring_router
from hubnisio.finance.transactions_api import router as transactions_router
from hubnisio.health.activities_api import router as activities_router
from hubnisio.health.api import router as health_router
from hubnisio.health.body_api import router as body_router
from hubnisio.health.recovery_api import router as recovery_router
from hubnisio.health.sleep_api import router as sleep_router
from hubnisio.jobs import app as job_app


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_auth_config(get_settings())
    # The API defers jobs (e.g. a bank's first sync), so it needs the queue open.
    async with job_app.open_async():
        yield


app = FastAPI(title="Hubnisio", version="0.1.0", lifespan=lifespan)
# Every router, by domain. A new one (e.g. health/sleep_api.py) is added here, nowhere else.
ROUTERS = (
    core_router,
    # Finance
    finance_router,
    transactions_router,
    organize_router,
    insights_router,
    investments_router,
    budgets_router,
    recurring_router,
    # Health
    health_router,
    activities_router,
    body_router,
    recovery_router,
    sleep_router,
)
for router in ROUTERS:
    app.include_router(router, prefix="/api")
