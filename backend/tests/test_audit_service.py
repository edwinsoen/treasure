from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.audit import service as audit_service_mod
from app.audit.sanitize import REDACTED


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset audit service module-level state between tests."""
    audit_service_mod._audit_client = None
    audit_service_mod._audit_collection = None
    audit_service_mod._owns_client = False
    yield
    audit_service_mod._audit_client = None
    audit_service_mod._audit_collection = None
    audit_service_mod._owns_client = False


class TestGetAuditCollection:
    def test_raises_when_not_initialised(self) -> None:
        with pytest.raises(RuntimeError, match="Audit DB not initialised"):
            audit_service_mod.get_audit_collection()


class TestLog:
    @pytest.fixture
    def mock_collection(self) -> AsyncMock:
        collection = AsyncMock()
        audit_service_mod._audit_collection = collection
        return collection

    async def test_inserts_entry(self, mock_collection: AsyncMock) -> None:
        await audit_service_mod.log(
            owner_id="owner1",
            actor="actor1",
            action="create",
            entity_type="account",
            entity_id="eid1",
            source="POST /api/accounts",
        )
        mock_collection.insert_one.assert_awaited_once()
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["owner_id"] == "owner1"
        assert doc["actor"] == "actor1"
        assert doc["action"] == "create"
        assert doc["entity_type"] == "account"
        assert doc["entity_id"] == "eid1"
        assert doc["source"] == "POST /api/accounts"
        assert doc["timestamp"] is not None

    async def test_includes_changes_and_params(self, mock_collection: AsyncMock) -> None:
        await audit_service_mod.log(
            owner_id="o",
            actor="a",
            action="update",
            entity_type="account",
            entity_id="e",
            source="PATCH /api/accounts/e",
            changes={"name": {"old": "A", "new": "B"}},
            params={"name": "B"},
        )
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["changes"] == {"name": {"old": "A", "new": "B"}}
        assert doc["params"] == {"name": "B"}

    async def test_sanitizes_sensitive_data(self, mock_collection: AsyncMock) -> None:
        await audit_service_mod.log(
            owner_id="o",
            actor="a",
            action="create",
            entity_type="user",
            entity_id="e",
            source="POST /api/auth/register",
            params={"email": "a@b.com", "password": "hunter2"},
        )
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["params"]["email"] == "a@b.com"
        assert doc["params"]["password"] == REDACTED

    async def test_catches_insert_error(self, mock_collection: AsyncMock) -> None:
        mock_collection.insert_one.side_effect = RuntimeError("connection lost")
        # Should not raise — audit failures are swallowed.
        await audit_service_mod.log(
            owner_id="o",
            actor="a",
            action="create",
            entity_type="account",
            entity_id="e",
            source="POST /api/accounts",
        )
        mock_collection.insert_one.assert_awaited_once()

    async def test_none_changes_and_params(self, mock_collection: AsyncMock) -> None:
        await audit_service_mod.log(
            owner_id="o",
            actor="a",
            action="login",
            entity_type="user",
            entity_id="e",
            source="POST /api/auth/login",
        )
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["changes"] is None
        assert doc["params"] is None


class TestInitAuditDb:
    async def test_creates_indexes(self) -> None:
        mock_client = MagicMock()
        mock_collection = AsyncMock()
        mock_client.__getitem__ = MagicMock(
            return_value=MagicMock(__getitem__=MagicMock(return_value=mock_collection))
        )

        with patch("app.audit.service.AsyncMongoClient", return_value=mock_client):
            await audit_service_mod.init_audit_db("mongodb://localhost:27017/test", "test")

        mock_collection.create_indexes.assert_awaited_once()
        indexes = mock_collection.create_indexes.call_args[0][0]
        index_names = [idx.document["name"] for idx in indexes]
        assert "ix_owner_entity_ts" in index_names
        assert "ix_owner_actor_ts" in index_names
        assert "ix_owner_ts" in index_names
        # No TTL index by default
        assert "ix_ttl" not in index_names

    async def test_creates_ttl_index_when_retention_set(self) -> None:
        mock_client = MagicMock()
        mock_collection = AsyncMock()
        mock_client.__getitem__ = MagicMock(
            return_value=MagicMock(__getitem__=MagicMock(return_value=mock_collection))
        )

        with patch("app.audit.service.AsyncMongoClient", return_value=mock_client):
            await audit_service_mod.init_audit_db(
                "mongodb://localhost:27017/test", "test", retention_days=30
            )

        indexes = mock_collection.create_indexes.call_args[0][0]
        index_names = [idx.document["name"] for idx in indexes]
        assert "ix_ttl" in index_names


class TestCloseAuditDb:
    async def test_closes_owned_client(self) -> None:
        mock_client = AsyncMock()
        audit_service_mod._audit_client = mock_client
        audit_service_mod._owns_client = True
        audit_service_mod._audit_collection = AsyncMock()

        await audit_service_mod.close_audit_db()

        mock_client.aclose.assert_awaited_once()
        assert audit_service_mod._audit_client is None
        assert audit_service_mod._audit_collection is None
        assert audit_service_mod._owns_client is False

    async def test_skips_close_when_not_owned(self) -> None:
        mock_client = AsyncMock()
        audit_service_mod._audit_client = mock_client
        audit_service_mod._owns_client = False

        await audit_service_mod.close_audit_db()

        mock_client.aclose.assert_not_awaited()
