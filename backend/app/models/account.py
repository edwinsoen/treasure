"""Account entity — Beanie Document and Pydantic schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from beanie import Document, PydanticObjectId
from bson import Decimal128
from pydantic import BaseModel, BeforeValidator, Field, field_validator
from pymongo import ASCENDING, IndexModel

from app.core.currencies import VALID_CURRENCY_CODES


def _to_decimal(v: object) -> Decimal:
    """Convert Decimal128 (from MongoDB) or other values to Decimal."""
    if isinstance(v, Decimal128):
        return v.to_decimal()
    return Decimal(str(v))


MongoDecimal = Annotated[Decimal, BeforeValidator(_to_decimal)]


class AccountType(StrEnum):
    bank_account = "bank_account"
    credit_card = "credit_card"
    investment = "investment"
    cash = "cash"
    stored_value = "stored_value"


# Account types that default to expects_alerts=True.
_ALERT_TYPES: frozenset[AccountType] = frozenset(
    {AccountType.bank_account, AccountType.credit_card}
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Account(Document):
    owner_id: PydanticObjectId
    created_by: PydanticObjectId
    name: str
    type: AccountType
    currency: str
    initial_balance: MongoDecimal = Decimal("0")
    balance: MongoDecimal = Decimal("0")
    expects_alerts: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "accounts"
        indexes = [
            IndexModel(
                [("owner_id", ASCENDING), ("name", ASCENDING)],
                unique=True,
            ),
            IndexModel([("owner_id", ASCENDING), ("type", ASCENDING)]),
            IndexModel([("owner_id", ASCENDING), ("is_active", ASCENDING)]),
        ]

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        code = v.upper()
        if code not in VALID_CURRENCY_CODES:
            raise ValueError(f"Invalid ISO 4217 currency code: {v}")
        return code


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class AccountCreate(BaseModel):
    name: str
    type: AccountType
    currency: str
    initial_balance: Decimal = Decimal("0")
    expects_alerts: bool | None = None  # None → derive from type

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        code = v.upper()
        if code not in VALID_CURRENCY_CODES:
            raise ValueError(f"Invalid ISO 4217 currency code: {v}")
        return code


class AccountUpdate(BaseModel):
    name: str | None = None
    expects_alerts: bool | None = None
    balance: Decimal | None = None
    is_active: bool | None = None


class AccountResponse(BaseModel):
    id: str
    owner_id: str
    created_by: str
    name: str
    type: AccountType
    currency: str
    initial_balance: Decimal
    balance: Decimal
    expects_alerts: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, doc: Account) -> AccountResponse:
        return cls(
            id=str(doc.id),
            owner_id=str(doc.owner_id),
            created_by=str(doc.created_by),
            name=doc.name,
            type=doc.type,
            currency=doc.currency,
            initial_balance=doc.initial_balance,
            balance=doc.balance,
            expects_alerts=doc.expects_alerts,
            is_active=doc.is_active,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
