"""Category repository."""

from __future__ import annotations

from beanie import PydanticObjectId
from beanie.exceptions import RevisionIdWasChanged
from pymongo.errors import DuplicateKeyError

from app.models.category import Category
from app.repositories.base import BaseRepository


class CategoryNameExistsError(Exception):
    """Raised when a category name/slug already exists for this owner."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Category with name '{name}' already exists")


class CategoryHasReferencesError(Exception):
    """Raised when attempting to delete a category referenced by transactions."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(f"Category is referenced by {count} transaction(s)")


class CategoryRepository(BaseRepository[Category]):
    model = Category

    async def create(self, doc: Category) -> Category:
        try:
            return await super().create(doc)
        except DuplicateKeyError:
            raise CategoryNameExistsError(doc.name) from None

    async def get_by_slug(self, slug: str) -> Category | None:
        return await self.model.find_one(self._scoped({"slug": slug}))

    async def list_all(
        self,
        type_filter: str | None = None,
        include_inactive: bool = False,
    ) -> list[Category]:
        filters: dict = {}
        if not include_inactive:
            filters["is_active"] = True
        if type_filter is not None:
            filters["type"] = type_filter
        return await self.find(filters, sort=[("sort_order", 1), ("name", 1)])

    async def find_children(self, parent_id: PydanticObjectId) -> list[Category]:
        return await self.find({"parent_id": parent_id}, sort=[("sort_order", 1), ("name", 1)])

    async def update(self, doc_id, updates: dict) -> Category | None:  # type: ignore[override]
        try:
            return await super().update(doc_id, updates)
        except (DuplicateKeyError, RevisionIdWasChanged):
            name = updates.get("name", "")
            raise CategoryNameExistsError(str(name)) from None

    async def count_referencing_transactions(self, category_id: PydanticObjectId) -> int:
        """Count transactions that reference this category.

        Uses raw PyMongo since the Transaction model may not exist yet (Story 2.3).
        """
        db = Category.get_pymongo_collection().database
        txn_col = db["transactions"]
        return await txn_col.count_documents(
            {
                "owner_id": self.owner_id,
                "$or": [
                    {"category_attributions.category_id": category_id},
                    {"line_items.category_id": category_id},
                ],
            }
        )
