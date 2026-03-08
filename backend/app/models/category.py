"""Category entity — Beanie Document and Pydantic schemas."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


class CategoryType(StrEnum):
    expense = "expense"
    income = "income"
    investment = "investment"
    giving = "giving"


class CategoryStatus(StrEnum):
    active = "active"
    suggested = "suggested"


def slugify(name: str) -> str:
    """Convert a category name to a URL-friendly slug.

    "Food Deliveries" → "food-deliveries"
    "Food & Drink"    → "food-drink"
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Category(Document):
    owner_id: PydanticObjectId
    created_by: PydanticObjectId
    name: str
    slug: str
    type: CategoryType
    parent_id: PydanticObjectId | None = None
    status: CategoryStatus = CategoryStatus.active
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "categories"
        indexes = [
            IndexModel(
                [("owner_id", ASCENDING), ("name", ASCENDING)],
                unique=True,
            ),
            IndexModel(
                [("owner_id", ASCENDING), ("slug", ASCENDING)],
                unique=True,
            ),
            IndexModel([("owner_id", ASCENDING), ("parent_id", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("type", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("is_active", ASCENDING)]),
        ]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CategoryCreate(BaseModel):
    name: str
    type: CategoryType | None = None  # Required for top-level; inferred for subcategory
    parent_slug: str | None = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    status: CategoryStatus | None = None


class CategoryResponse(BaseModel):
    id: str
    owner_id: str
    created_by: str
    name: str
    slug: str
    type: CategoryType
    parent_slug: str | None
    status: CategoryStatus
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, doc: Category, parent_slug: str | None = None) -> CategoryResponse:
        return cls(
            id=str(doc.id),
            owner_id=str(doc.owner_id),
            created_by=str(doc.created_by),
            name=doc.name,
            slug=doc.slug,
            type=doc.type,
            parent_slug=parent_slug,
            status=doc.status,
            sort_order=doc.sort_order,
            is_active=doc.is_active,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )


class CategoryTreeResponse(BaseModel):
    id: str
    owner_id: str
    created_by: str
    name: str
    slug: str
    type: CategoryType
    parent_slug: None = None
    status: CategoryStatus
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    children: list[CategoryResponse]

    @classmethod
    def from_doc(cls, doc: Category, children: list[CategoryResponse]) -> CategoryTreeResponse:
        return cls(
            id=str(doc.id),
            owner_id=str(doc.owner_id),
            created_by=str(doc.created_by),
            name=doc.name,
            slug=doc.slug,
            type=doc.type,
            status=doc.status,
            sort_order=doc.sort_order,
            is_active=doc.is_active,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            children=children,
        )
