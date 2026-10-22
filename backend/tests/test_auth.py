import uuid

import pytest
from fastapi import HTTPException

from hubnisio.cli import bootstrap
from hubnisio.core.auth import check_auth_config, get_principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import HouseholdRole
from hubnisio.core.settings import Settings, get_settings


@pytest.fixture
def dev_user_email(monkeypatch: pytest.MonkeyPatch) -> str:
    email = f"dev-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setenv("HUBNISIO_DEV_USER_EMAIL", email)
    get_settings.cache_clear()
    return email


@pytest.mark.anyio
async def test_principal_is_the_bootstrapped_owner(
    migrated_database: str, dev_user_email: str
) -> None:
    assert await bootstrap(dev_user_email.upper(), "Dev", "Home") == 0

    async with get_sessionmaker()() as session:
        principal = await get_principal(session)

    assert principal.role is HouseholdRole.OWNER


@pytest.mark.anyio
async def test_missing_dev_user_is_a_clear_error(
    migrated_database: str, dev_user_email: str
) -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(HTTPException) as raised:
            await get_principal(session)

    assert raised.value.status_code == 503
    assert "bootstrap" in raised.value.detail


def test_api_refuses_to_start_outside_development() -> None:
    check_auth_config(Settings(database_url="postgresql://unused", environment="development"))

    with pytest.raises(RuntimeError, match="only runs with HUBNISIO_ENVIRONMENT=development"):
        check_auth_config(Settings(database_url="postgresql://unused", environment="production"))
