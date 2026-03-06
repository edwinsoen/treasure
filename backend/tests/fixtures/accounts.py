"""Default Account document fixtures."""

from __future__ import annotations

from decimal import Decimal

from beanie import PydanticObjectId

# Stable owner/creator IDs used across account fixtures.
FIXTURE_OWNER_ID = PydanticObjectId("aaaaaaaaaaaaaaaaaaaaaaaa")


def default_accounts() -> list[dict]:
    """A small set of accounts for integration tests."""
    return [
        {
            "owner_id": FIXTURE_OWNER_ID,
            "created_by": FIXTURE_OWNER_ID,
            "name": "Main Checking",
            "type": "bank_account",
            "currency": "USD",
            "initial_balance": Decimal("1000"),
            "balance": Decimal("1000"),
            "expects_alerts": True,
            "is_active": True,
        },
        {
            "owner_id": FIXTURE_OWNER_ID,
            "created_by": FIXTURE_OWNER_ID,
            "name": "Visa Card",
            "type": "credit_card",
            "currency": "USD",
            "initial_balance": Decimal("0"),
            "balance": Decimal("0"),
            "expects_alerts": True,
            "is_active": True,
        },
        {
            "owner_id": FIXTURE_OWNER_ID,
            "created_by": FIXTURE_OWNER_ID,
            "name": "Petty Cash",
            "type": "cash",
            "currency": "USD",
            "initial_balance": Decimal("200"),
            "balance": Decimal("200"),
            "expects_alerts": False,
            "is_active": False,
        },
    ]
