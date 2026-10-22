import pytest
from httpx import ASGITransport, AsyncClient

from hubnisio.main import app

pytestmark = pytest.mark.anyio


async def test_health_reports_database_ok(migrated_database: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
