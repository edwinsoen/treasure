from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

from app.audit import service as audit_service_mod
from app.audit.queries import query_audit_log


def _make_doc(
    *,
    oid: str | None = None,
    owner_id: str = "owner1",
    entity_type: str = "account",
    entity_id: str = "eid1",
) -> dict[str, object]:
    """Build a minimal audit doc with a generated _id."""
    return {
        "_id": ObjectId(oid) if oid else ObjectId(),
        "timestamp": datetime.now(UTC),
        "owner_id": owner_id,
        "actor": "actor1",
        "action": "create",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": "POST /api/accounts",
        "changes": None,
        "params": None,
    }


@pytest.fixture(autouse=True)
def _reset_audit_state():
    audit_service_mod._audit_collection = None
    yield
    audit_service_mod._audit_collection = None


def _setup_collection(docs: list[dict[str, object]]) -> AsyncMock:
    """Wire up a mock collection that returns *docs* from find().sort().limit().to_list()."""
    mock_collection = AsyncMock()

    to_list = AsyncMock(return_value=docs)
    limit = MagicMock()
    limit.to_list = to_list
    sort = MagicMock()
    sort.limit = MagicMock(return_value=limit)
    find = MagicMock()
    find.sort = MagicMock(return_value=sort)
    mock_collection.find = MagicMock(return_value=find)

    audit_service_mod._audit_collection = mock_collection
    return mock_collection


class TestQueryAuditLog:
    async def test_filters_by_owner_id(self) -> None:
        mock = _setup_collection([])
        await query_audit_log(owner_id="owner1")
        query = mock.find.call_args[0][0]
        assert query["owner_id"] == "owner1"

    async def test_filters_by_entity_type(self) -> None:
        mock = _setup_collection([])
        await query_audit_log(owner_id="o", entity_type="account")
        query = mock.find.call_args[0][0]
        assert query["entity_type"] == "account"

    async def test_filters_by_entity_id(self) -> None:
        mock = _setup_collection([])
        await query_audit_log(owner_id="o", entity_id="eid1")
        query = mock.find.call_args[0][0]
        assert query["entity_id"] == "eid1"

    async def test_filters_by_actor(self) -> None:
        mock = _setup_collection([])
        await query_audit_log(owner_id="o", actor="actor1")
        query = mock.find.call_args[0][0]
        assert query["actor"] == "actor1"

    async def test_filters_by_date_range(self) -> None:
        mock = _setup_collection([])
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        await query_audit_log(owner_id="o", start_date=start, end_date=end)
        query = mock.find.call_args[0][0]
        assert query["timestamp"]["$gte"] == start
        assert query["timestamp"]["$lte"] == end

    async def test_cursor_pagination(self) -> None:
        cursor_id = "507f1f77bcf86cd799439011"
        mock = _setup_collection([])
        await query_audit_log(owner_id="o", cursor=cursor_id)
        query = mock.find.call_args[0][0]
        assert query["_id"] == {"$lt": ObjectId(cursor_id)}

    async def test_returns_items_and_no_next_cursor_on_last_page(self) -> None:
        docs = [_make_doc() for _ in range(3)]
        _setup_collection(docs)
        result = await query_audit_log(owner_id="owner1", limit=50)
        assert len(result["items"]) == 3
        assert result["next_cursor"] is None

    async def test_returns_next_cursor_when_more_pages(self) -> None:
        # limit=2, so we request 3 docs. Return 3 to signal "more available".
        docs = [_make_doc() for _ in range(3)]
        _setup_collection(docs)
        result = await query_audit_log(owner_id="owner1", limit=2)
        assert len(result["items"]) == 2
        assert result["next_cursor"] == str(docs[1]["_id"])

    async def test_empty_result(self) -> None:
        _setup_collection([])
        result = await query_audit_log(owner_id="owner1")
        assert result["items"] == []
        assert result["next_cursor"] is None

    async def test_doc_to_entry_formats_timestamp(self) -> None:
        docs = [_make_doc()]
        _setup_collection(docs)
        result = await query_audit_log(owner_id="owner1")
        entry = result["items"][0]
        # timestamp should be an ISO format string
        datetime.fromisoformat(entry["timestamp"])  # should not raise
