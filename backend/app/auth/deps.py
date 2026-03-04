from __future__ import annotations

import hashlib
from dataclasses import dataclass

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException, Request, status
from fastapi_users import FastAPIUsers

from app.audit.context import AuditContext
from app.auth.backend import auth_backend
from app.auth.manager import get_user_manager
from app.models.user import User

fastapi_users = FastAPIUsers[User, PydanticObjectId](get_user_manager, [auth_backend])

# Cookie-authenticated user (optional — None if not authenticated via cookie)
_optional_cookie_user = fastapi_users.current_user(active=True, optional=True)


async def get_current_user(
    request: Request,
    cookie_user: User | None = Depends(_optional_cookie_user),
) -> User:
    """Resolve the current user from session cookie or X-API-Key header."""
    if cookie_user is not None:
        return cookie_user

    api_key = request.headers.get("X-API-Key")
    if api_key:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        user = await User.find_one(
            User.api_key_hash == key_hash, User.is_active == True  # noqa: E712
        )
        if user is not None:
            return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


@dataclass
class UserContext:
    """Owner identity injected into every protected request.

    For v1 single-user, owner_id and created_by are both the authenticated user's id.
    When multi-user auth is added, only this dependency changes.
    """

    owner_id: PydanticObjectId
    created_by: PydanticObjectId


async def get_user_context(
    request: Request,
    user: User = Depends(get_current_user),
) -> UserContext:
    assert user.id is not None  # always set for users retrieved from the database

    # Propagate actor to the audit middleware via request.state.
    audit_ctx: AuditContext | None = getattr(request.state, "audit_context", None)
    if audit_ctx is not None:
        audit_ctx.actor = str(user.id)

    return UserContext(owner_id=user.id, created_by=user.id)
