"""Auth endpoint tests.

Smoke tests — no DB required.
Integration tests — require live MongoDB; skipped automatically if unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.fixtures.users import ADMIN_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD

# ---------------------------------------------------------------------------
# Smoke tests — no DB required
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    with (
        patch("app.api.health.ping_database", new_callable=AsyncMock, return_value=True),
        patch("app.core.db.connect", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.asyncio
async def test_login_endpoint_exists(mock_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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


# ---------------------------------------------------------------------------
# Integration tests — require live MongoDB (via seed_db → mongo_db)
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(seed_db):
    """
    ASGI test client with the app running against Beanie already initialised
    by the session mongo_db fixture. The app lifespan's connect/disconnect and
    audit calls are patched to no-ops so they don't conflict with the session
    connection.

    Uses https://test so the Secure flag on session cookies is honoured and
    cookies are forwarded on subsequent requests within the same client.
    """
    with (
        patch("app.core.db.connect", new_callable=AsyncMock),
        patch("app.core.db.disconnect", new_callable=AsyncMock),
        patch("app.audit.service.init_audit_db", new_callable=AsyncMock),
        patch("app.audit.service.close_audit_db", new_callable=AsyncMock),
        patch("app.auth.manager.audit_log", new_callable=AsyncMock),
        patch("app.main.resolve_encryption_key"),
        patch(
            "app.api.audit_log.query_audit_log",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None},
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as http:
            yield http


class TestLogin:
    async def test_success_returns_session_cookie(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert response.status_code == 204
        assert "treasure_session" in response.cookies

    async def test_wrong_password_returns_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/auth/login",
            data={"username": ADMIN_EMAIL, "password": "wrong-password"},
        )
        assert response.status_code == 400

    async def test_unknown_email_returns_400(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/auth/login",
            data={"username": "nobody@example.com", "password": ADMIN_PASSWORD},
        )
        assert response.status_code == 400


class TestGetMe:
    async def test_returns_user_after_login(self, client: AsyncClient) -> None:
        await client.post(
            "/api/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        response = await client.get("/api/users/me")

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == ADMIN_EMAIL
        assert body["display_name"] == "Admin"

    async def test_unauthenticated_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/api/users/me")
        assert response.status_code == 401


class TestLogout:
    async def test_session_invalidated_after_logout(self, client: AsyncClient) -> None:
        await client.post(
            "/api/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 204

        response = await client.get("/api/users/me")
        assert response.status_code == 401


class TestApiKey:
    async def test_valid_key_authenticates(self, client: AsyncClient) -> None:
        # /api/audit-log uses Depends(get_user_context) → get_current_user,
        # which supports X-API-Key. /api/users/me uses fastapi-users' cookie-only auth.
        response = await client.get(
            "/api/audit-log",
            headers={"X-API-Key": ADMIN_API_KEY},
        )
        assert response.status_code == 200

    async def test_invalid_key_returns_401(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/audit-log",
            headers={"X-API-Key": "tsr_notavalidkey"},
        )
        assert response.status_code == 401
