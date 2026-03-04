from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.audit.middleware import _entity_id_from_body, _entity_id_from_path
from app.main import app


@pytest.fixture
def mock_db():
    """Patch DB and audit so startup doesn't need a live MongoDB."""
    with (
        patch("app.core.db.connect", new_callable=AsyncMock),
        patch("app.audit.service.init_audit_db", new_callable=AsyncMock),
    ):
        yield


class TestEntityIdFromPath:
    def test_extracts_objectid_from_resource_path(self) -> None:
        assert _entity_id_from_path("/api/accounts/507f1f77bcf86cd799439011") == (
            "507f1f77bcf86cd799439011"
        )

    def test_extracts_last_objectid(self) -> None:
        path = "/api/accounts/507f1f77bcf86cd799439011/items/507f1f77bcf86cd799439012"
        assert _entity_id_from_path(path) == "507f1f77bcf86cd799439012"

    def test_returns_none_for_no_objectid(self) -> None:
        assert _entity_id_from_path("/api/accounts") is None

    def test_returns_none_for_short_hex(self) -> None:
        assert _entity_id_from_path("/api/accounts/abc123") is None

    def test_handles_trailing_slash(self) -> None:
        assert _entity_id_from_path("/api/accounts/507f1f77bcf86cd799439011/") == (
            "507f1f77bcf86cd799439011"
        )


class TestEntityIdFromBody:
    def test_extracts_id_from_json(self) -> None:
        body = b'{"id": "507f1f77bcf86cd799439011", "name": "test"}'
        assert _entity_id_from_body(body) == "507f1f77bcf86cd799439011"

    def test_returns_none_for_no_id(self) -> None:
        assert _entity_id_from_body(b'{"name": "test"}') is None

    def test_returns_none_for_invalid_json(self) -> None:
        assert _entity_id_from_body(b"not json") is None

    def test_returns_none_for_non_dict(self) -> None:
        assert _entity_id_from_body(b"[1, 2, 3]") is None

    def test_returns_none_for_empty_body(self) -> None:
        assert _entity_id_from_body(b"") is None


class TestAuditLogMiddleware:
    async def test_no_entry_for_get_request(self, mock_db: None) -> None:
        """GET requests should never produce audit entries."""
        with (
            patch("app.audit.middleware.audit_log", new_callable=AsyncMock) as mock_log,
            patch("app.api.health.ping_database", new_callable=AsyncMock, return_value=True),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/health")
        assert response.status_code == 200
        mock_log.assert_not_awaited()

    async def test_no_entry_when_action_not_set(self, mock_db: None) -> None:
        """POST to login without annotating action from middleware perspective.
        The audit entry comes from the hook, not the middleware."""
        with patch("app.audit.middleware.audit_log", new_callable=AsyncMock) as mock_log:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Login with invalid creds → 422 (no action set, no middleware entry)
                response = await client.post("/api/auth/login")
            assert response.status_code == 422
            mock_log.assert_not_awaited()

    async def test_no_entry_for_unauthenticated_401(self, mock_db: None) -> None:
        """401 responses should not produce audit entries."""
        with patch("app.audit.middleware.audit_log", new_callable=AsyncMock) as mock_log:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/users/me")
            assert response.status_code == 401
            mock_log.assert_not_awaited()
