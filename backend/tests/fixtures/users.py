"""Default User document fixtures.

Each function returns a list of dicts that can be inserted as User documents.
Tests that need different users can define their own fixture functions and
pass them to seed_db instead of (or in addition to) these defaults.
"""

from __future__ import annotations

import hashlib

from fastapi_users.password import PasswordHelper

_helper = PasswordHelper()

# Stable credentials used directly in tests — do not change without updating tests.
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-test-password-123"
ADMIN_API_KEY = "tsr_test_default_api_key_fixture_00"


def default_users() -> list[dict]:
    """One superuser with a known password and API key."""
    return [
        {
            "email": ADMIN_EMAIL,
            "hashed_password": _helper.hash(ADMIN_PASSWORD),
            "display_name": "Admin",
            "is_active": True,
            "is_superuser": True,
            "is_verified": True,
            "api_key_hash": hashlib.sha256(ADMIN_API_KEY.encode()).hexdigest(),
        }
    ]
