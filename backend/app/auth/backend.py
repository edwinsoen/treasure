from __future__ import annotations

from fastapi import Depends
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users_db_beanie.access_token import BeanieAccessTokenDatabase

from app.models.user import AccessToken

_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

cookie_transport = CookieTransport(
    cookie_name="treasure_session",
    cookie_max_age=_COOKIE_MAX_AGE,
    cookie_httponly=True,
    cookie_samesite="lax",
)


async def get_access_token_db():
    yield BeanieAccessTokenDatabase(AccessToken)


def get_database_strategy(
    access_token_db: AccessTokenDatabase[AccessToken] = Depends(get_access_token_db),
) -> DatabaseStrategy:
    return DatabaseStrategy(access_token_db, lifetime_seconds=_COOKIE_MAX_AGE)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
