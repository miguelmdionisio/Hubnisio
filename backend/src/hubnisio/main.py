"""HTTP API entrypoint: `uvicorn hubnisio.main:app`."""

from fastapi import FastAPI

from hubnisio.core.routes import router as core_router

app = FastAPI(title="Hubnisio", version="0.1.0")
app.include_router(core_router, prefix="/api")
