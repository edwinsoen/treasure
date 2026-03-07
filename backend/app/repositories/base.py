"""Base repository with mandatory owner_id scoping."""

from __future__ import annotations

from datetime import UTC, datetime

from beanie import Document, PydanticObjectId


class BaseRepository[TDocument: Document]:
    """Abstract base repository that enforces owner_id on every query.

    Subclasses set ``model`` to the concrete Beanie Document type.
    Every query method prepends ``{"owner_id": self.owner_id}`` so individual
    repositories cannot accidentally bypass tenant isolation.
    """

    model: type[TDocument]

    def __init__(self, owner_id: PydanticObjectId) -> None:
        self.owner_id = owner_id

    def _scoped(self, extra: dict | None = None) -> dict:
        """Return a filter dict that always includes owner_id."""
        base: dict = {"owner_id": self.owner_id}
        if extra:
            base.update(extra)
        return base

    async def create(self, doc: TDocument) -> TDocument:
        """Insert a new document. Caller must have set owner_id on the doc."""
        await doc.insert()
        return doc

    async def get_by_id(self, doc_id: PydanticObjectId) -> TDocument | None:
        """Fetch a single document by ID, scoped to owner_id."""
        return await self.model.find_one(self._scoped({"_id": doc_id}))

    async def find(
        self,
        filters: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[TDocument]:
        """Find documents matching *filters*, scoped to owner_id."""
        query = self.model.find(self._scoped(filters))
        if sort:
            query = query.sort(sort)
        return await query.to_list()

    async def update(self, doc_id: PydanticObjectId, updates: dict) -> TDocument | None:
        """Update a document by ID. Returns the updated document or None."""
        doc = await self.get_by_id(doc_id)
        if doc is None:
            return None
        updates["updated_at"] = datetime.now(UTC)
        await doc.set(updates)
        return doc

    async def soft_delete(self, doc_id: PydanticObjectId) -> TDocument | None:
        """Soft-delete by setting is_active=False."""
        return await self.update(doc_id, {"is_active": False})
