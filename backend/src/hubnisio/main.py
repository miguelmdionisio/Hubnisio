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
from hubnisio.jobs import app as job_app


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_auth_config(get_settings())
    # The API defers jobs (e.g. a bank's first sync), so it needs the queue open.
    async with job_app.open_async():
        yield


app = FastAPI(title="Hubnisio", version="0.1.0", lifespan=lifespan)
app.include_router(core_router, prefix="/api")
app.include_router(finance_router, prefix="/api")
app.include_router(transactions_router, prefix="/api")
app.include_router(organize_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(investments_router, prefix="/api")
app.include_router(budgets_router, prefix="/api")
app.include_router(recurring_router, prefix="/api")
