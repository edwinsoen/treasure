from __future__ import annotations

from typing import Any

import structlog
from beanie import PydanticObjectId
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, exceptions
from fastapi_users.db import BeanieUserDatabase

from app.core.config import get_settings
from app.models.user import User

logger = structlog.get_logger()


class ObjectIDIDMixin:
    """Parse and validate PydanticObjectId user IDs."""

    def parse_id(self, value: Any) -> PydanticObjectId:
        try:
            return PydanticObjectId(value)
        except Exception as exc:
            raise exceptions.InvalidID() from exc


async def get_user_db():
    yield BeanieUserDatabase(User)


class UserManager(ObjectIDIDMixin, BaseUserManager[User, PydanticObjectId]):
    @property
    def reset_password_token_secret(self) -> str:  # type: ignore[override]
        return get_settings().auth_secret.get_secret_value()

    @property
    def verification_token_secret(self) -> str:  # type: ignore[override]
        return get_settings().auth_secret.get_secret_value()

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response=None,
    ) -> None:
        logger.info("User logged in", user_id=str(user.id))

    async def on_after_logout(self, user: User, request: Request | None = None) -> None:
        logger.info("User logged out", user_id=str(user.id))


async def get_user_manager(user_db: BeanieUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)
