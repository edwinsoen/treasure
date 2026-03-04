from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient, IndexModel

from app.audit.sanitize import sanitize_dict

if TYPE_CHECKING:
    from pymongo.asynchronous.collection import AsyncCollection

logger = structlog.get_logger()

# Module-level singleton, mirrors the pattern in core/db.py.
_audit_client: AsyncMongoClient | None = None
_audit_collection: AsyncCollection | None = None
_owns_client: bool = False


async def init_audit_db(
    mongodb_uri: str,
    db_name: str,
    *,
    collection_name: str = "audit_log",
    retention_days: int | None = None,
) -> None:
    """Create the audit database connection and ensure indexes exist.

    Called during app lifespan startup.  Uses its own ``AsyncMongoClient`` so the
    audit collection can optionally live in a different database.
    """
    global _audit_client, _audit_collection, _owns_client

    _audit_client = AsyncMongoClient(mongodb_uri)
    _owns_client = True
    _audit_collection = _audit_client[db_name][collection_name]

    indexes: list[IndexModel] = [
        IndexModel(
            [
                ("owner_id", ASCENDING),
                ("entity_type", ASCENDING),
                ("entity_id", ASCENDING),
                ("timestamp", DESCENDING),
            ],
            name="ix_owner_entity_ts",
        ),
        IndexModel(
            [("owner_id", ASCENDING), ("actor", ASCENDING), ("timestamp", DESCENDING)],
            name="ix_owner_actor_ts",
        ),
        IndexModel(
            [("owner_id", ASCENDING), ("timestamp", DESCENDING)],
            name="ix_owner_ts",
        ),
    ]

    if retention_days is not None:
        indexes.append(
            IndexModel(
                [("timestamp", ASCENDING)],
                name="ix_ttl",
                expireAfterSeconds=retention_days * 86400,
            )
        )

    await _audit_collection.create_indexes(indexes)
    logger.info(
        "Audit DB ready",
        db=db_name,
        collection=collection_name,
        ttl_days=retention_days,
    )


async def close_audit_db() -> None:
    """Close the audit database connection if we own it."""
    global _audit_client, _audit_collection, _owns_client
    if _owns_client and _audit_client is not None:
        await _audit_client.aclose()
    _audit_client = None
    _audit_collection = None
    _owns_client = False
    logger.info("Audit DB disconnected")


def get_audit_collection() -> AsyncCollection:
    """Return the audit collection.  Raises ``RuntimeError`` if not initialised."""
    if _audit_collection is None:
        raise RuntimeError("Audit DB not initialised — call init_audit_db() first")
    return _audit_collection


async def log(
    *,
    owner_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    source: str,
    changes: dict[str, object] | None = None,
    params: dict[str, object] | None = None,
) -> None:
    """Write a single audit log entry.

    Awaits the write for correctness.  On failure the error is logged but never
    propagated — audit failures must not break requests.
    """
    collection = get_audit_collection()

    entry: dict[str, object] = {
        "timestamp": datetime.now(UTC),
        "owner_id": owner_id,
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": source,
        "changes": sanitize_dict(changes),
        "params": sanitize_dict(params),
    }

    try:
        await collection.insert_one(entry)
    except Exception:
        logger.exception(
            "Failed to write audit entry",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
        )
