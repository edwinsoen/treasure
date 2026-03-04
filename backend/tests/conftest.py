"""Shared pytest fixtures and environment setup.

Module-level os.environ calls run before any test file imports app modules,
so required settings are available when app.main is first imported.
"""

from __future__ import annotations

import os

# Set all required settings before app.main is imported during test collection.
# Use setdefault so values already in the environment (e.g., from a local .env) win.
os.environ.setdefault("TSR_APP_ENV", "test")
os.environ.setdefault("TSR_LOG_LEVEL", "INFO")
os.environ.setdefault("TSR_MONGODB_URI", "mongodb://localhost:27017/treasure_test")
os.environ.setdefault("TSR_AUTH_SECRET", "test-auth-secret-that-is-32-chars!!")

import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Ensure each test starts with a fresh settings instance."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Database fixtures — session-scoped connection, function-scoped seeding
#
# Imports of app.models.user and beanie are deferred to inside the fixtures so
# they happen after test-file collection has already imported app.main.
# Importing app.models.user at module level here triggers a circular import via
# fastapi_users_db_beanie → fastapi_users.db, causing BeanieUserDatabase to
# silently fail to register before app.auth.manager can import it.
# ---------------------------------------------------------------------------


@pytest.fixture
async def mongo_db():
    """
    Connect to the test MongoDB and initialise Beanie once for the whole session.
    Tests that request this fixture (directly or via seed_db) are skipped if
    MongoDB is not reachable.
    """
    import pymongo.errors
    from beanie import init_beanie
    from pymongo import AsyncMongoClient

    from app.core.db import get_db_name
    from app.models.user import AccessToken, User

    uri = os.environ.get("TSR_MONGODB_URI", "mongodb://localhost:27017/treasure_test")
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        await client.admin.command("ping")
    except pymongo.errors.ServerSelectionTimeoutError:
        await client.aclose()
        pytest.skip("MongoDB not available")

    db_name = get_db_name(uri)
    await init_beanie(database=client[db_name], document_models=[User, AccessToken])

    yield client[db_name]

    await client.aclose()


@pytest.fixture
async def seed_db(mongo_db):
    """
    Seed the default fixtures before each test and wipe them after.

    Individual test files can define their own seed fixture that calls this one
    and inserts additional documents, or they can skip this and manage their own
    data using the mongo_db database handle directly.
    """
    from app.models.user import AccessToken, User
    from tests.fixtures.users import default_users

    for data in default_users():
        await User(**data).create()

    yield

    await AccessToken.find_all().delete()
    await User.find_all().delete()
