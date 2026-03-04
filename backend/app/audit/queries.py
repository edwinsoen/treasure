from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from bson import ObjectId

from app.audit.service import get_audit_collection


class AuditEntry(TypedDict):
    id: str
    timestamp: str
    owner_id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    source: str
    changes: dict[str, object] | None
    params: dict[str, object] | None


class AuditPage(TypedDict):
    items: list[AuditEntry]
    next_cursor: str | None


def _doc_to_entry(doc: dict[str, object]) -> AuditEntry:
    """Convert a raw MongoDB document to a typed audit entry."""
    ts = doc["timestamp"]
    ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
    return AuditEntry(
        id=str(doc["_id"]),
        timestamp=ts_str,
        owner_id=str(doc["owner_id"]),
        actor=str(doc["actor"]),
        action=str(doc["action"]),
        entity_type=str(doc["entity_type"]),
        entity_id=str(doc["entity_id"]),
        source=str(doc["source"]),
        changes=doc.get("changes"),  # type: ignore[arg-type]
        params=doc.get("params"),  # type: ignore[arg-type]
    )


async def query_audit_log(
    *,
    owner_id: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AuditPage:
    """Query audit log entries with filters and cursor-based pagination.

    Results are ordered newest-first (``_id`` descending).  Pass
    ``next_cursor`` from the previous response as *cursor* to fetch the next
    page.
    """
    collection = get_audit_collection()

    query: dict[str, object] = {"owner_id": owner_id}

    if entity_type is not None:
        query["entity_type"] = entity_type
    if entity_id is not None:
        query["entity_id"] = entity_id
    if actor is not None:
        query["actor"] = actor

    if start_date is not None or end_date is not None:
        ts_filter: dict[str, datetime] = {}
        if start_date is not None:
            ts_filter["$gte"] = start_date if start_date.tzinfo else start_date.replace(tzinfo=UTC)
        if end_date is not None:
            ts_filter["$lte"] = end_date if end_date.tzinfo else end_date.replace(tzinfo=UTC)
        query["timestamp"] = ts_filter

    if cursor is not None:
        query["_id"] = {"$lt": ObjectId(cursor)}

    docs: list[dict[str, object]] = (
        await collection.find(query).sort("_id", -1).limit(limit + 1).to_list(limit + 1)
    )

    has_next = len(docs) > limit
    if has_next:
        docs = docs[:limit]

    items = [_doc_to_entry(doc) for doc in docs]
    next_cursor = str(docs[-1]["_id"]) if has_next and docs else None

    return AuditPage(items=items, next_cursor=next_cursor)
