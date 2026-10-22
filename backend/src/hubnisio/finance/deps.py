"""FastAPI dependencies shared by the finance routers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal, get_principal
from hubnisio.core.db import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
