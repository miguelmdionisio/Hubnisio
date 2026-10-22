"""HTTP endpoints owned by the core module."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.db import get_session

router = APIRouter(tags=["core"])


class Health(BaseModel):
    status: str
    database: str


@router.get(
    "/health",
    operation_id="getHealth",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Health}},
)
async def health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> Health:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="degraded", database="unavailable")
    return Health(status="ok", database="ok")
