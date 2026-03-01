from __future__ import annotations

from fastapi_users_db_beanie import BeanieBaseUserDocument
from fastapi_users_db_beanie.access_token import BeanieBaseAccessTokenDocument


class User(BeanieBaseUserDocument):
    display_name: str = "Admin"
    # SHA-256 hex digest of the raw API key — None means no key issued yet
    api_key_hash: str | None = None

    class Settings(BeanieBaseUserDocument.Settings):
        name = "users"


class AccessToken(BeanieBaseAccessTokenDocument):
    class Settings(BeanieBaseAccessTokenDocument.Settings):
        name = "access_tokens"
