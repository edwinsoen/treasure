"""Category CRUD API endpoints."""

from __future__ import annotations

import jsonpatch
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.audit.context import AuditContext
from app.auth.deps import UserContext, get_user_context
from app.models.category import (
    Category,
    CategoryCreate,
    CategoryResponse,
    CategoryTreeResponse,
    CategoryType,
    CategoryUpdate,
    slugify,
)
from app.repositories.category import CategoryNameExistsError, CategoryRepository

router = APIRouter()

# Fields that clients may modify via PATCH.
_PATCHABLE_FIELDS = frozenset(CategoryUpdate.model_fields.keys())


def _repo(ctx: UserContext) -> CategoryRepository:
    return CategoryRepository(owner_id=ctx.owner_id)


def _audit(request: Request, action: str) -> None:
    audit_ctx: AuditContext | None = getattr(request.state, "audit_context", None)
    if audit_ctx is not None:
        audit_ctx.action = action
        audit_ctx.entity_type = "category"


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryCreate,
    request: Request,
    ctx: UserContext = Depends(get_user_context),
) -> CategoryResponse:
    repo = _repo(ctx)
    slug = slugify(body.name)

    parent_slug_value: str | None = None
    parent_id: PydanticObjectId | None = None
    category_type: CategoryType

    if body.parent_slug is not None:
        # Subcategory creation — resolve parent
        parent = await repo.get_by_slug(body.parent_slug)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent category '{body.parent_slug}' not found",
            )
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot create subcategory of a subcategory (max 2 levels)",
            )
        if body.type is not None and body.type != parent.type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Type '{body.type}' does not match parent type '{parent.type}'",
            )
        category_type = parent.type
        parent_id = parent.id
        parent_slug_value = parent.slug
    else:
        # Top-level category — type is required
        if body.type is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'type' is required for top-level categories",
            )
        category_type = body.type

    doc = Category(
        owner_id=ctx.owner_id,
        created_by=ctx.created_by,
        name=body.name,
        slug=slug,
        type=category_type,
        parent_id=parent_id,
        sort_order=body.sort_order,
    )
    try:
        created = await repo.create(doc)
    except CategoryNameExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category with name '{body.name}' already exists",
        ) from None

    _audit(request, "create")
    return CategoryResponse.from_doc(created, parent_slug=parent_slug_value)


@router.get("/categories")
async def list_categories(
    ctx: UserContext = Depends(get_user_context),
    type: CategoryType | None = None,
    include_inactive: bool = False,
) -> list[CategoryTreeResponse]:
    """Return categories as a nested tree."""
    repo = _repo(ctx)
    all_cats = await repo.list_all(type_filter=type, include_inactive=include_inactive)

    # Separate top-level and children
    top_level: list[Category] = []
    children_map: dict[PydanticObjectId, list[Category]] = {}
    slug_map: dict[PydanticObjectId, str] = {}

    for cat in all_cats:
        assert cat.id is not None
        slug_map[cat.id] = cat.slug
        if cat.parent_id is None:
            top_level.append(cat)
        else:
            children_map.setdefault(cat.parent_id, []).append(cat)

    # Build tree
    result: list[CategoryTreeResponse] = []
    for parent in top_level:
        assert parent.id is not None
        kids = children_map.get(parent.id, [])
        child_responses = [CategoryResponse.from_doc(c, parent_slug=parent.slug) for c in kids]
        result.append(CategoryTreeResponse.from_doc(parent, children=child_responses))

    return result


@router.get("/categories/{slug}")
async def get_category(
    slug: str,
    ctx: UserContext = Depends(get_user_context),
) -> CategoryTreeResponse | CategoryResponse:
    repo = _repo(ctx)
    doc = await repo.get_by_slug(slug)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Subcategory — resolve parent slug
    if doc.parent_id is not None:
        parent_slug: str | None = None
        parent = await repo.get_by_id(doc.parent_id)
        if parent is not None:
            parent_slug = parent.slug
        return CategoryResponse.from_doc(doc, parent_slug=parent_slug)

    # Top-level — include children
    assert doc.id is not None
    kids = await repo.find_children(doc.id)
    child_responses = [CategoryResponse.from_doc(c, parent_slug=doc.slug) for c in kids]
    return CategoryTreeResponse.from_doc(doc, children=child_responses)


@router.patch("/categories/{slug}")
async def patch_category(
    slug: str,
    request: Request,
    ctx: UserContext = Depends(get_user_context),
) -> CategoryResponse:
    """Update a category via JSON Patch (RFC 6902).

    Only ``name``, ``sort_order``, and ``status`` are patchable.
    Changing ``name`` also regenerates the ``slug``.
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
    repo = _repo(ctx)
    doc = await repo.get_by_slug(slug)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Apply patch to a dict of the current patchable fields.
    current = {f: getattr(doc, f) for f in _PATCHABLE_FIELDS if getattr(doc, f, None) is not None}
    # Convert enums to their string values for JSON patching.
    for k, v in current.items():
        if hasattr(v, "value"):
            current[k] = v.value

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
        validated = CategoryUpdate.model_validate(patched)
    except ValidationError as exc:
        errors = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
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

    # If name changed, regenerate slug.
    if "name" in updates:
        updates["slug"] = slugify(updates["name"])

    assert doc.id is not None
    try:
        updated = await repo.update(doc.id, updates)
    except CategoryNameExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category with name '{updates.get('name', '')}' already exists",
        ) from None

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Resolve parent slug
    parent_slug: str | None = None
    if updated.parent_id is not None:
        parent = await repo.get_by_id(updated.parent_id)
        if parent is not None:
            parent_slug = parent.slug

    _audit(request, "update")
    return CategoryResponse.from_doc(updated, parent_slug=parent_slug)


@router.delete("/categories/{slug}")
async def delete_category(
    slug: str,
    request: Request,
    ctx: UserContext = Depends(get_user_context),
) -> CategoryResponse:
    repo = _repo(ctx)
    doc = await repo.get_by_slug(slug)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    assert doc.id is not None

    # Count transaction references for this category.
    ref_count = await repo.count_referencing_transactions(doc.id)

    # If top-level, also check children.
    children: list[Category] = []
    if doc.parent_id is None:
        children = await repo.find_children(doc.id)
        for child in children:
            assert child.id is not None
            ref_count += await repo.count_referencing_transactions(child.id)

    if ref_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete category: {ref_count} transaction(s) reference it",
        )

    # Cascade soft-delete children first.
    for child in children:
        assert child.id is not None
        await repo.soft_delete(child.id)

    deleted = await repo.soft_delete(doc.id)
    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Resolve parent slug
    parent_slug: str | None = None
    if deleted.parent_id is not None:
        parent = await repo.get_by_id(deleted.parent_id)
        if parent is not None:
            parent_slug = parent.slug

    _audit(request, "delete")
    return CategoryResponse.from_doc(deleted, parent_slug=parent_slug)
