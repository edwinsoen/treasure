"""Auth endpoint smoke tests.

These tests verify that auth routes are registered and return the expected
HTTP status codes for unauthenticated access. Full integration tests
(login, session management, API key) require a live MongoDB instance
and will be added when a shared test-DB fixture is in place.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def mock_db():
    """Patch DB ping so health/startup doesn't need a live MongoDB."""
    with (
        patch("app.api.health.ping_database", new_callable=AsyncMock, return_value=True),
        patch("app.core.db.connect", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.asyncio
async def test_login_endpoint_exists(mock_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # POST with no body → 422 Unprocessable Entity (endpoint exists but input is invalid)
        response = await client.post("/api/auth/login")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_protected_me_requires_auth(mock_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_is_public(mock_db) -> None:
    with patch("app.api.health.ping_database", new_callable=AsyncMock, return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/health")
    assert response.status_code == 200
