from __future__ import annotations

from beanie import PydanticObjectId
from fastapi_users import schemas


class UserRead(schemas.BaseUser[PydanticObjectId]):
    display_name: str


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None
