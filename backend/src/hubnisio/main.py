"""HTTP API entrypoint: `uvicorn hubnisio.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hubnisio.core.auth import check_auth_config
from hubnisio.core.routes import router as core_router
from hubnisio.core.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_auth_config(get_settings())
    yield


app = FastAPI(title="Hubnisio", version="0.1.0", lifespan=lifespan)
app.include_router(core_router, prefix="/api")
