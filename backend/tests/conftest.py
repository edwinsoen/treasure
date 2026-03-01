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
