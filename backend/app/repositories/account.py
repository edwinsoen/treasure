"""Account repository."""

from __future__ import annotations

from beanie.exceptions import RevisionIdWasChanged
from pymongo.errors import DuplicateKeyError

from app.models.account import Account, AccountType
from app.repositories.base import BaseRepository


class AccountNameExistsError(Exception):
    """Raised when an account name already exists for this owner."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Account with name '{name}' already exists")


class AccountRepository(BaseRepository[Account]):
    model = Account

    async def create(self, doc: Account) -> Account:
        try:
            return await super().create(doc)
        except DuplicateKeyError:
            raise AccountNameExistsError(doc.name) from None

    async def find_by_name(self, name: str) -> Account | None:
        return await self.model.find_one(self._scoped({"name": name}))

    async def list_accounts(
        self,
        type_filter: AccountType | None = None,
        is_active_filter: bool | None = None,
    ) -> list[Account]:
        filters: dict = {}
        if type_filter is not None:
            filters["type"] = type_filter
        if is_active_filter is not None:
            filters["is_active"] = is_active_filter
        return await self.find(filters, sort=[("name", 1)])

    async def update(self, doc_id, updates: dict) -> Account | None:  # type: ignore[override]
        try:
            return await super().update(doc_id, updates)
        except (DuplicateKeyError, RevisionIdWasChanged):
            name = updates.get("name", "")
            raise AccountNameExistsError(str(name)) from None
