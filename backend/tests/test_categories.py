"""Category endpoint tests.

Smoke tests — no DB required.
Integration tests — require live MongoDB; skipped automatically if unavailable.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.fixtures.categories import (
    DINING,
    GROCERIES,
    NONEXISTENT_SLUG,
)
from tests.fixtures.users import ADMIN_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD

_JSON_PATCH = "application/json-patch+json"

# ---------------------------------------------------------------------------
# Smoke tests — no DB required
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    with (
        patch(
            "app.api.health.ping_database",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.core.db.connect", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.asyncio
async def test_list_categories_requires_auth(mock_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/categories")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_category_requires_auth(mock_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/categories", json=GROCERIES)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Integration tests — require live MongoDB
# ---------------------------------------------------------------------------

_TEST_URI = os.environ.get("TSR_MONGODB_URI", "mongodb://localhost:27017/treasure_test")


@pytest.fixture
async def audit_db(mongo_db):
    """Initialise the audit service against the real test database."""
    from app.audit.service import close_audit_db, init_audit_db
    from app.core.db import get_db_name

    db_name = get_db_name(_TEST_URI)
    await init_audit_db(_TEST_URI, db_name)
    yield
    await mongo_db["audit_log"].delete_many({})
    await close_audit_db()


@pytest.fixture
async def client(seed_db, audit_db):
    """ASGI test client backed by a real MongoDB instance."""
    with (
        patch("app.core.db.connect", new_callable=AsyncMock),
        patch("app.core.db.disconnect", new_callable=AsyncMock),
        patch("app.main.resolve_encryption_key"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as http:
            resp = await http.post(
                "/api/auth/login",
                data={
                    "username": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                },
            )
            assert resp.status_code == 204
            yield http


def _json_patch(client: AsyncClient, path: str, ops: list[dict]):
    """Send a JSON Patch (RFC 6902) request."""
    return client.patch(
        path,
        content=json.dumps(ops).encode(),
        headers={"Content-Type": _JSON_PATCH},
    )


async def _create_category(client: AsyncClient, **overrides) -> dict:
    """Create a category and return the response body."""
    data = {**GROCERIES, **overrides}
    resp = await client.post("/api/categories", json=data)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/categories — happy path
# ---------------------------------------------------------------------------


class TestCreateCategory:
    async def test_create_top_level_returns_201(self, client: AsyncClient) -> None:
        resp = await client.post("/api/categories", json=GROCERIES)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Groceries"
        assert body["slug"] == "groceries"
        assert body["type"] == "expense"
        assert body["parent_slug"] is None
        assert body["status"] == "active"
        assert body["sort_order"] == 0
        assert body["is_active"] is True
        assert "id" in body
        assert "owner_id" in body
        assert "created_at" in body
        assert "updated_at" in body

    async def test_create_subcategory(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        resp = await client.post(
            "/api/categories",
            json={"name": "Supermarket", "parent_slug": parent["slug"]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Supermarket"
        assert body["slug"] == "supermarket"
        assert body["type"] == "expense"  # inherited from parent
        assert body["parent_slug"] == "groceries"

    async def test_subcategory_type_inferred_from_parent(self, client: AsyncClient) -> None:
        parent = await _create_category(client, name="Salary", type="income")
        resp = await client.post(
            "/api/categories",
            json={"name": "Base Pay", "parent_slug": parent["slug"]},
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "income"

    async def test_subcategory_type_mismatch_returns_422(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        resp = await client.post(
            "/api/categories",
            json={"name": "Wrong Type", "type": "income", "parent_slug": parent["slug"]},
        )
        assert resp.status_code == 422
        assert "does not match parent type" in resp.json()["detail"]

    async def test_sub_of_sub_returns_422(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        child = await _create_category(client, name="Supermarket", parent_slug=parent["slug"])
        resp = await client.post(
            "/api/categories",
            json={"name": "Aisle 5", "parent_slug": child["slug"]},
        )
        assert resp.status_code == 422
        assert "max 2 levels" in resp.json()["detail"].lower()

    async def test_parent_slug_not_found_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/categories",
            json={"name": "Orphan", "parent_slug": NONEXISTENT_SLUG},
        )
        assert resp.status_code == 404

    async def test_duplicate_name_returns_409(self, client: AsyncClient) -> None:
        await _create_category(client)
        resp = await client.post("/api/categories", json=GROCERIES)
        assert resp.status_code == 409

    async def test_slug_auto_generated(self, client: AsyncClient) -> None:
        cat = await _create_category(client, name="Food & Drink")
        assert cat["slug"] == "food-drink"

    async def test_missing_type_for_top_level_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/categories", json={"name": "No Type"})
        assert resp.status_code == 422
        assert "type" in resp.json()["detail"].lower()

    async def test_custom_sort_order(self, client: AsyncClient) -> None:
        cat = await _create_category(client, sort_order=5)
        assert cat["sort_order"] == 5


# ---------------------------------------------------------------------------
# POST /api/categories — validation / invalid input
# ---------------------------------------------------------------------------


class TestCreateCategoryValidation:
    async def test_missing_name(self, client: AsyncClient) -> None:
        resp = await client.post("/api/categories", json={"type": "expense"})
        assert resp.status_code == 422

    async def test_empty_body(self, client: AsyncClient) -> None:
        resp = await client.post("/api/categories", json={})
        assert resp.status_code == 422

    async def test_malformed_json(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/categories",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    async def test_no_body(self, client: AsyncClient) -> None:
        resp = await client.post("/api/categories")
        assert resp.status_code == 422

    async def test_invalid_type_enum(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/categories",
            json={"name": "Bad Type", "type": "not_a_type"},
        )
        assert resp.status_code == 422

    async def test_extra_unknown_fields_ignored(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/categories",
            json={**GROCERIES, "unknown_field": "ignored"},
        )
        assert resp.status_code == 201
        assert "unknown_field" not in resp.json()

    async def test_empty_name_is_accepted(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/categories",
            json={"name": "", "type": "expense"},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/categories — tree endpoint
# ---------------------------------------------------------------------------


class TestListCategories:
    async def test_returns_tree_structure(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        await _create_category(client, name="Supermarket", parent_slug=parent["slug"])
        await _create_category(client, name="Farmers Market", parent_slug=parent["slug"])

        resp = await client.get("/api/categories")
        assert resp.status_code == 200
        tree = resp.json()
        assert len(tree) == 1
        assert tree[0]["slug"] == "groceries"
        assert len(tree[0]["children"]) == 2
        child_slugs = {c["slug"] for c in tree[0]["children"]}
        assert "supermarket" in child_slugs
        assert "farmers-market" in child_slugs

    async def test_filter_by_type(self, client: AsyncClient) -> None:
        await _create_category(client)  # expense
        await _create_category(client, name="Salary", type="income")

        resp = await client.get("/api/categories", params={"type": "income"})
        assert resp.status_code == 200
        tree = resp.json()
        assert len(tree) == 1
        assert tree[0]["type"] == "income"

    async def test_include_inactive(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        await client.delete(f"/api/categories/{cat['slug']}")

        # Default: inactive hidden
        resp = await client.get("/api/categories")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        # With include_inactive
        resp = await client.get("/api/categories", params={"include_inactive": "true"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["is_active"] is False

    async def test_sort_order_respected(self, client: AsyncClient) -> None:
        await _create_category(client, name="Zzz Last", sort_order=10)
        await _create_category(client, name="Aaa First", sort_order=0)

        resp = await client.get("/api/categories")
        assert resp.status_code == 200
        tree = resp.json()
        assert tree[0]["slug"] == "aaa-first"
        assert tree[1]["slug"] == "zzz-last"

    async def test_empty_list(self, client: AsyncClient) -> None:
        resp = await client.get("/api/categories")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/categories/{slug}
# ---------------------------------------------------------------------------


class TestGetCategory:
    async def test_get_by_slug(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await client.get(f"/api/categories/{cat['slug']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Groceries"
        assert resp.json()["parent_slug"] is None
        assert resp.json()["children"] == []

    async def test_get_parent_includes_children(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        await _create_category(client, name="Supermarket", parent_slug=parent["slug"])
        await _create_category(client, name="Farmers Market", parent_slug=parent["slug"])
        resp = await client.get(f"/api/categories/{parent['slug']}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["children"]) == 2
        names = {c["name"] for c in body["children"]}
        assert names == {"Supermarket", "Farmers Market"}
        for c in body["children"]:
            assert c["parent_slug"] == parent["slug"]

    async def test_get_subcategory_has_parent_slug(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        child = await _create_category(client, name="Supermarket", parent_slug=parent["slug"])
        resp = await client.get(f"/api/categories/{child['slug']}")
        assert resp.status_code == 200
        assert resp.json()["parent_slug"] == "groceries"
        assert "children" not in resp.json()

    async def test_get_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/categories/{NONEXISTENT_SLUG}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/categories/{slug} — RFC 6902 JSON Patch — happy path
# ---------------------------------------------------------------------------


class TestPatchCategory:
    async def test_replace_name_updates_slug(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [{"op": "replace", "path": "/name", "value": "Fresh Produce"}],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Fresh Produce"
        assert body["slug"] == "fresh-produce"

    async def test_replace_sort_order(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [{"op": "replace", "path": "/sort_order", "value": 99}],
        )
        assert resp.status_code == 200
        assert resp.json()["sort_order"] == 99

    async def test_replace_status(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [{"op": "replace", "path": "/status", "value": "suggested"}],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "suggested"

    async def test_test_op_passes(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [
                {"op": "test", "path": "/name", "value": "Groceries"},
                {"op": "replace", "path": "/name", "value": "Tested"},
            ],
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Tested"

    async def test_test_op_fails_returns_409(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [
                {"op": "test", "path": "/name", "value": "Wrong Name"},
                {"op": "replace", "path": "/name", "value": "Nope"},
            ],
        )
        assert resp.status_code == 409

    async def test_patch_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await _json_patch(
            client,
            f"/api/categories/{NONEXISTENT_SLUG}",
            [{"op": "replace", "path": "/name", "value": "X"}],
        )
        assert resp.status_code == 404

    async def test_patch_duplicate_name_returns_409(self, client: AsyncClient) -> None:
        await _create_category(client)
        cat2 = await _create_category(client, **DINING)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat2['slug']}",
            [{"op": "replace", "path": "/name", "value": "Groceries"}],
        )
        assert resp.status_code == 409

    async def test_replace_multiple_fields(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [
                {"op": "replace", "path": "/name", "value": "Updated"},
                {"op": "replace", "path": "/sort_order", "value": 42},
            ],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Updated"
        assert body["sort_order"] == 42


# ---------------------------------------------------------------------------
# PATCH /api/categories/{slug} — validation / invalid input
# ---------------------------------------------------------------------------


class TestPatchCategoryValidation:
    async def test_empty_patch_array_returns_422(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(client, f"/api/categories/{cat['slug']}", [])
        assert resp.status_code == 422

    async def test_slug_not_patchable_returns_422(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [{"op": "replace", "path": "/slug", "value": "hacked"}],
        )
        assert resp.status_code == 422
        assert "not patchable" in resp.json()["detail"].lower()

    async def test_type_not_patchable_returns_422(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [{"op": "replace", "path": "/type", "value": "income"}],
        )
        assert resp.status_code == 422
        assert "not patchable" in resp.json()["detail"].lower()

    async def test_malformed_json_returns_422(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await client.patch(
            f"/api/categories/{cat['slug']}",
            content=b"not json",
            headers={"Content-Type": _JSON_PATCH},
        )
        assert resp.status_code == 422

    async def test_unsupported_content_type_returns_415(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await client.patch(
            f"/api/categories/{cat['slug']}",
            content=b'[{"op": "replace", "path": "/name", "value": "X"}]',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    async def test_put_method_not_allowed(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await client.put(
            f"/api/categories/{cat['slug']}",
            json={"name": "X"},
        )
        assert resp.status_code == 405

    async def test_object_body_instead_of_array_returns_422(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await client.patch(
            f"/api/categories/{cat['slug']}",
            content=b'{"name": "X"}',
            headers={"Content-Type": _JSON_PATCH},
        )
        assert resp.status_code == 422

    async def test_missing_op_field_returns_422(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await _json_patch(
            client,
            f"/api/categories/{cat['slug']}",
            [{"path": "/name", "value": "X"}],
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/categories/{slug}
# ---------------------------------------------------------------------------


class TestDeleteCategory:
    async def test_soft_delete(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        resp = await client.delete(f"/api/categories/{cat['slug']}")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_delete_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.delete(f"/api/categories/{NONEXISTENT_SLUG}")
        assert resp.status_code == 404

    async def test_delete_with_transaction_refs_returns_409(
        self, client: AsyncClient, mongo_db
    ) -> None:
        """Insert a fake transaction referencing this category, then try to delete."""
        cat = await _create_category(client)

        from bson import ObjectId

        cat_id = ObjectId(cat["id"])
        owner_id = ObjectId(cat["owner_id"])
        await mongo_db["transactions"].insert_one(
            {
                "owner_id": owner_id,
                "category_attributions": [{"category_id": cat_id, "amount": 10}],
            }
        )
        try:
            resp = await client.delete(f"/api/categories/{cat['slug']}")
            assert resp.status_code == 409
            assert "1 transaction(s)" in resp.json()["detail"]
        finally:
            await mongo_db["transactions"].delete_many({})

    async def test_delete_parent_cascades_to_children(self, client: AsyncClient) -> None:
        parent = await _create_category(client)
        child = await _create_category(client, name="Supermarket", parent_slug=parent["slug"])

        resp = await client.delete(f"/api/categories/{parent['slug']}")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # Child should also be soft-deleted
        child_resp = await client.get(f"/api/categories/{child['slug']}")
        assert child_resp.status_code == 200
        assert child_resp.json()["is_active"] is False

    async def test_deleted_visible_with_include_inactive(self, client: AsyncClient) -> None:
        cat = await _create_category(client)
        await client.delete(f"/api/categories/{cat['slug']}")

        # Direct GET still works
        resp = await client.get(f"/api/categories/{cat['slug']}")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


class TestSeedCategories:
    async def test_seeds_when_no_categories_exist(self, seed_db, mongo_db) -> None:
        from app.cli.seed_categories import seed_default_categories
        from app.models.category import Category
        from app.models.user import User

        user = await User.find_one()
        assert user is not None and user.id is not None

        count = await seed_default_categories(owner_id=user.id, created_by=user.id)
        assert count > 0

        # Verify categories were created in the DB
        cats = await Category.find({"owner_id": user.id}).to_list()
        assert len(cats) == count

        # Verify hierarchy: some should have parent_id set
        parents = [c for c in cats if c.parent_id is None]
        children = [c for c in cats if c.parent_id is not None]
        assert len(parents) > 0
        assert len(children) > 0

    async def test_skips_when_categories_already_exist(self, seed_db, mongo_db) -> None:
        from app.cli.seed_categories import seed_default_categories
        from app.models.category import Category
        from app.models.user import User

        user = await User.find_one()
        assert user is not None and user.id is not None

        # First seed
        first_count = await seed_default_categories(owner_id=user.id, created_by=user.id)
        assert first_count > 0

        # Second seed — should be a no-op
        second_count = await seed_default_categories(owner_id=user.id, created_by=user.id)
        assert second_count == 0

        # Count unchanged
        cats = await Category.find({"owner_id": user.id}).to_list()
        assert len(cats) == first_count

    async def test_skips_when_user_has_custom_category(
        self, client: AsyncClient, seed_db, mongo_db
    ) -> None:
        """If the user already created categories manually, seeding is skipped."""
        from app.cli.seed_categories import seed_default_categories
        from app.models.category import Category
        from app.models.user import User

        # Create one category via API
        await _create_category(client)

        user = await User.find_one()
        assert user is not None and user.id is not None

        count = await seed_default_categories(owner_id=user.id, created_by=user.id)
        assert count == 0

        # Only the one manually created category exists
        cats = await Category.find({"owner_id": user.id}).to_list()
        assert len(cats) == 1


# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------


class TestApiKeyAuth:
    async def test_api_key_works_for_categories(self, client: AsyncClient) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as http:
            resp = await http.get(
                "/api/categories",
                headers={"X-API-Key": ADMIN_API_KEY},
            )
            assert resp.status_code == 200
