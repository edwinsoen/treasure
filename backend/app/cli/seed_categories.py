"""Seed default categories from JSON configuration."""

from __future__ import annotations

import json
from pathlib import Path

from beanie import PydanticObjectId

from app.models.category import Category, CategoryStatus, CategoryType, slugify

_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "default_categories.json"


async def seed_default_categories(
    owner_id: PydanticObjectId,
    created_by: PydanticObjectId,
) -> int:
    """Load default categories from JSON if none exist for this owner.

    Returns the number of categories created (0 if skipped).
    """
    existing = await Category.find_one({"owner_id": owner_id})
    if existing is not None:
        return 0

    data = json.loads(_DATA_PATH.read_text())
    count = 0

    for cat_data in data:
        parent = Category(
            owner_id=owner_id,
            created_by=created_by,
            name=cat_data["name"],
            slug=slugify(cat_data["name"]),
            type=CategoryType(cat_data["type"]),
            sort_order=cat_data.get("sort_order", 0),
            status=CategoryStatus.active,
        )
        await parent.insert()
        count += 1

        for child_data in cat_data.get("children", []):
            child = Category(
                owner_id=owner_id,
                created_by=created_by,
                name=child_data["name"],
                slug=slugify(child_data["name"]),
                type=parent.type,
                parent_id=parent.id,
                sort_order=child_data.get("sort_order", 0),
                status=CategoryStatus.active,
            )
            await child.insert()
            count += 1

    return count
