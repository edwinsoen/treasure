"""treasure-setup — one-time initial user creation.

Usage (local):
    uv run treasure-setup

Usage (Docker):
    docker compose exec backend treasure-setup

Run once after first deployment. Safe to re-run — exits early if a user already exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import sys
from getpass import getpass

import structlog
from beanie import init_beanie
from fastapi_users.password import PasswordHelper
from pymongo import AsyncMongoClient

from app.audit.service import close_audit_db, init_audit_db
from app.audit.service import log as audit_log
from app.core.config import get_settings, resolve_encryption_key
from app.core.db import get_db_name
from app.models.user import AccessToken, User

logger = structlog.get_logger()


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


async def _run() -> None:
    settings = get_settings()
    mongodb_uri = settings.mongodb_uri.get_secret_value()
    db_name = get_db_name(mongodb_uri)

    audit_uri = (
        settings.audit_mongodb_uri.get_secret_value()
        if settings.audit_mongodb_uri is not None
        else mongodb_uri
    )

    client = AsyncMongoClient(mongodb_uri)
    try:
        await init_beanie(
            database=client[db_name],
            document_models=[User, AccessToken],
        )
        await init_audit_db(
            audit_uri,
            get_db_name(audit_uri),
            retention_days=settings.audit_retention_days,
        )

        existing = await User.find_one()
        if existing is not None:
            print(f"A user already exists ({existing.email}). Nothing to do.")
            return

        print("=== Treasure — initial setup ===\n")
        email = _prompt("Email", "admin@localhost")
        display_name = _prompt("Display name", "Admin")

        password = getpass("Password: ")
        confirm = getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            sys.exit(1)
        if len(password) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            sys.exit(1)

        issue_api_key = input("Generate an API key for headless access? [y/N]: ").strip().lower()
        raw_api_key: str | None = None
        api_key_hash: str | None = None
        if issue_api_key == "y":
            raw_api_key = "tsr_" + secrets.token_urlsafe(32)
            api_key_hash = hashlib.sha256(raw_api_key.encode()).hexdigest()

        password_helper = PasswordHelper()
        user = User(
            email=email,
            hashed_password=password_helper.hash(password),
            display_name=display_name,
            is_active=True,
            is_superuser=True,
            is_verified=True,
            api_key_hash=api_key_hash,
        )
        await user.create()

        # Audit the user creation
        assert user.id is not None
        await audit_log(
            owner_id=str(user.id),
            actor=str(user.id),
            action="create",
            entity_type="user",
            entity_id=str(user.id),
            source="treasure-setup",
            params={"email": email, "display_name": display_name},
        )

        # Ensure the encryption key file exists
        resolve_encryption_key(settings)

        print(f"\nUser created: {user.email} (id: {user.id})")
        if raw_api_key:
            print(f"API key: {raw_api_key}")
            print("Save this key — it will not be shown again.")

    finally:
        await close_audit_db()
        await client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
