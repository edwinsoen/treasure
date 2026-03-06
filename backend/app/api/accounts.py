"""Account CRUD API endpoints."""

from __future__ import annotations

import jsonpatch
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.audit.context import AuditContext
from app.auth.deps import UserContext, get_user_context
from app.models.account import (
    _ALERT_TYPES,
    Account,
    AccountCreate,
    AccountResponse,
    AccountType,
    AccountUpdate,
)
from app.repositories.account import AccountNameExistsError, AccountRepository

router = APIRouter()

# Fields that clients may modify via PATCH.
_PATCHABLE_FIELDS = frozenset(AccountUpdate.model_fields.keys())


def _repo(ctx: UserContext) -> AccountRepository:
    return AccountRepository(owner_id=ctx.owner_id)


def _audit(request: Request, action: str) -> None:
    audit_ctx: AuditContext | None = getattr(
        request.state, "audit_context", None
    )
    if audit_ctx is not None:
        audit_ctx.action = action
        audit_ctx.entity_type = "account"


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(
    body: AccountCreate,
    request: Request,
    ctx: UserContext = Depends(get_user_context),
) -> AccountResponse:
    expects_alerts = (
        body.expects_alerts
        if body.expects_alerts is not None
        else body.type in _ALERT_TYPES
    )
    doc = Account(
        owner_id=ctx.owner_id,
        created_by=ctx.created_by,
        name=body.name,
        type=body.type,
        currency=body.currency,
        initial_balance=body.initial_balance,
        balance=body.initial_balance,
        expects_alerts=expects_alerts,
    )
    try:
        created = await _repo(ctx).create(doc)
    except AccountNameExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Account with name '{body.name}' already exists",
        ) from None
    _audit(request, "create")
    return AccountResponse.from_doc(created)


@router.get("/accounts")
async def list_accounts(
    ctx: UserContext = Depends(get_user_context),
    type: AccountType | None = None,
    is_active: bool | None = None,
) -> list[AccountResponse]:
    docs = await _repo(ctx).list_accounts(
        type_filter=type, is_active_filter=is_active
    )
    return [AccountResponse.from_doc(d) for d in docs]


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: PydanticObjectId,
    ctx: UserContext = Depends(get_user_context),
) -> AccountResponse:
    doc = await _repo(ctx).get_by_id(account_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    return AccountResponse.from_doc(doc)


@router.patch("/accounts/{account_id}")
async def patch_account(
    account_id: PydanticObjectId,
    request: Request,
    ctx: UserContext = Depends(get_user_context),
) -> AccountResponse:
    """Update an account via JSON Patch (RFC 6902).

    Request body: a JSON array of patch operations.
    Content-Type: application/json-patch+json

    Example::

        [
          {"op": "replace", "path": "/name", "value": "Primary Checking"},
          {"op": "test", "path": "/currency", "value": "USD"}
        ]

    Only paths under ``/_PATCHABLE_FIELDS`` are accepted.
    """
    content_type = (request.headers.get("content-type") or "").split(";")[0]
    if content_type not in {
        "application/json-patch+json",
        "application/json",
    }:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Use application/json-patch+json",
        )

    raw = await request.body()
    try:
        patch = jsonpatch.JsonPatch.from_string(raw)
    except (jsonpatch.InvalidJsonPatch, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid JSON Patch document (RFC 6902)",
        ) from None

    if not list(patch):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Patch document must not be empty",
        )

    # Validate that every operation targets a patchable field.
    for op in patch:
        path = op.get("path", "")
        field = path.lstrip("/").split("/")[0]
        if field not in _PATCHABLE_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '/{field}' is not patchable",
            )

    # Fetch current state.
    doc = await _repo(ctx).get_by_id(account_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Apply patch to a dict of the current patchable fields.
    current = {
        f: getattr(doc, f)
        for f in _PATCHABLE_FIELDS
        if getattr(doc, f, None) is not None
    }
    # Serialize Decimal → str for JSON-safe patching.
    for k, v in current.items():
        if hasattr(v, "as_tuple"):
            current[k] = str(v)

    try:
        patched = patch.apply(current)
    except jsonpatch.JsonPatchConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Patch conflict: {exc}",
        ) from None
    except jsonpatch.JsonPatchTestFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Test operation failed: {exc}",
        ) from None

    # Validate the patched result through the schema.
    try:
        validated = AccountUpdate.model_validate(patched)
    except ValidationError as exc:
        errors = [
            {k: v for k, v in e.items() if k != "ctx"}
            for e in exc.errors()
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        ) from None

    updates = validated.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Patch produced no effective changes",
        )

    try:
        updated = await _repo(ctx).update(account_id, updates)
    except AccountNameExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Account with name '{updates.get('name', '')}' "
                "already exists"
            ),
        ) from None

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    _audit(request, "update")
    return AccountResponse.from_doc(updated)


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: PydanticObjectId,
    request: Request,
    ctx: UserContext = Depends(get_user_context),
) -> AccountResponse:
    doc = await _repo(ctx).soft_delete(account_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    _audit(request, "delete")
    return AccountResponse.from_doc(doc)
