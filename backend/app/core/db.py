from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog
from beanie import init_beanie
from pymongo import AsyncMongoClient

if TYPE_CHECKING:
    from beanie import Document

logger = structlog.get_logger()

_db_client: AsyncMongoClient | None = None
# Set to True after the first init_beanie call (indexes created).
# With gunicorn preload_app=True, workers inherit this flag via fork,
# so subsequent connect() calls skip index creation.
_indexes_initialized: bool = False


def get_db_client() -> AsyncMongoClient:
    if _db_client is None:
        raise RuntimeError("DB client not initialised — call connect() first")
    return _db_client


def get_db_name(mongodb_uri: str) -> str:
    """Extract the database name from a MongoDB URI."""
    path = urlparse(mongodb_uri).path.lstrip("/")
    db_name = path.split("?")[0]
    if not db_name:
        raise ValueError(f"MongoDB URI must include a database name: {mongodb_uri}")
    return db_name


async def connect(mongodb_uri: str, document_models: list[type[Document]]) -> None:
    """Create the PyMongo async client and initialise Beanie document models."""
    global _db_client, _indexes_initialized
    _db_client = AsyncMongoClient(mongodb_uri)
    db_name = get_db_name(mongodb_uri)
    await init_beanie(
        database=_db_client[db_name],
        document_models=document_models,
        skip_indexes=_indexes_initialized,
    )
    _indexes_initialized = True
    logger.info("Database connected", db=db_name)


async def disconnect() -> None:
    global _db_client
    if _db_client is not None:
        await _db_client.aclose()
        _db_client = None
        logger.info("Database disconnected")


async def ping_database(timeout: float = 2.0) -> bool:
    """Return True if MongoDB responds to a ping within *timeout* seconds."""
    try:
        client = get_db_client()
        await asyncio.wait_for(client.admin.command("ping"), timeout=timeout)
        return True
    except Exception:
        return False
