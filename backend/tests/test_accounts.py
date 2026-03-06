"""Account endpoint tests.

Smoke tests — no DB required.
Integration tests — require live MongoDB; skipped automatically if unavailable.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
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
async def test_list_accounts_requires_auth(mock_db) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/accounts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_account_requires_auth(mock_db) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/accounts",
            json={"name": "X", "type": "cash", "currency": "USD"},
        )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Integration tests — require live MongoDB
# ---------------------------------------------------------------------------

_TEST_URI = os.environ.get(
    "TSR_MONGODB_URI", "mongodb://localhost:27017/treasure_test"
)


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
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://test"
        ) as http:
            resp = await http.post(
                "/api/auth/login",
                data={
                    "username": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                },
            )
            assert resp.status_code == 204
            yield http


CHECKING = {"name": "Checking", "type": "bank_account", "currency": "USD"}
SAVINGS = {"name": "Savings", "type": "bank_account", "currency": "USD"}

NONEXISTENT_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"


def _json_patch(client: AsyncClient, path: str, ops: list[dict]):
    """Send a JSON Patch (RFC 6902) request."""
    return client.patch(
        path,
        content=json.dumps(ops).encode(),
        headers={"Content-Type": _JSON_PATCH},
    )


# ---------------------------------------------------------------------------
# POST /api/accounts — happy path
# ---------------------------------------------------------------------------


class TestCreateAccount:
    async def test_create_returns_201(self, client: AsyncClient) -> None:
        resp = await client.post("/api/accounts", json=CHECKING)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Checking"
        assert body["type"] == "bank_account"
        assert body["currency"] == "USD"
        assert body["is_active"] is True
        assert "id" in body
        assert "owner_id" in body
        assert "created_at" in body
        assert "updated_at" in body

    async def test_balance_starts_at_initial_balance(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/accounts",
            json={
                "name": "With Balance",
                "type": "cash",
                "currency": "EUR",
                "initial_balance": "500.50",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(body["initial_balance"]) == Decimal("500.50")
        assert Decimal(body["balance"]) == Decimal("500.50")

    async def test_expects_alerts_defaults_true_for_bank(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post("/api/accounts", json=CHECKING)
        assert resp.status_code == 201
        assert resp.json()["expects_alerts"] is True

    async def test_expects_alerts_defaults_false_for_cash(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/accounts",
            json={"name": "Wallet", "type": "cash", "currency": "USD"},
        )
        assert resp.status_code == 201
        assert resp.json()["expects_alerts"] is False

    async def test_expects_alerts_override(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/accounts",
            json={
                "name": "Silent Bank",
                "type": "bank_account",
                "currency": "USD",
                "expects_alerts": False,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["expects_alerts"] is False

    async def test_duplicate_name_returns_409(
        self, client: AsyncClient
    ) -> None:
        resp1 = await client.post("/api/accounts", json=CHECKING)
        assert resp1.status_code == 201
        resp2 = await client.post("/api/accounts", json=CHECKING)
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/accounts — validation / invalid input
# ---------------------------------------------------------------------------


class TestCreateAccountValidation:
    async def test_missing_name(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/accounts",
            json={"type": "cash", "currency": "USD"},
        )
        assert resp.status_code == 422

    async def test_missing_type(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/accounts",
            json={"name": "No Type", "currency": "USD"},
        )
        assert resp.status_code == 422

    async def test_missing_currency(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/accounts",
            json={"name": "No Currency", "type": "cash"},
        )
        assert resp.status_code == 422

    async def test_empty_body(self, client: AsyncClient) -> None:
        resp = await client.post("/api/accounts", json={})
        assert resp.status_code == 422

    async def test_malformed_json(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/accounts",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    async def test_no_body(self, client: AsyncClient) -> None:
        resp = await client.post("/api/accounts")
        assert resp.status_code == 422

    async def test_invalid_currency(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/accounts",
            json={"name": "Bad", "type": "cash", "currency": "XXX"},
        )
        assert resp.status_code == 422

    async def test_invalid_type_enum(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/accounts",
            json={
                "name": "Bad Type",
                "type": "checking",
                "currency": "USD",
            },
        )
        assert resp.status_code == 422

    async def test_invalid_initial_balance_type(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/accounts",
            json={
                "name": "Bad Balance",
                "type": "cash",
                "currency": "USD",
                "initial_balance": "not_a_number",
            },
        )
        assert resp.status_code == 422

    async def test_empty_name_is_accepted(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/accounts",
            json={"name": "", "type": "cash", "currency": "USD"},
        )
        assert resp.status_code == 201

    async def test_extra_unknown_fields_ignored(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/accounts",
            json={
                "name": "Extra Fields",
                "type": "cash",
                "currency": "USD",
                "unknown_field": "ignored",
            },
        )
        assert resp.status_code == 201
        assert "unknown_field" not in resp.json()


# ---------------------------------------------------------------------------
# GET /api/accounts
# ---------------------------------------------------------------------------


class TestListAccounts:
    async def test_list_returns_created(self, client: AsyncClient) -> None:
        await client.post("/api/accounts", json=CHECKING)
        await client.post("/api/accounts", json=SAVINGS)
        resp = await client.get("/api/accounts")
        assert resp.status_code == 200
        names = {a["name"] for a in resp.json()}
        assert "Checking" in names
        assert "Savings" in names

    async def test_filter_by_type(self, client: AsyncClient) -> None:
        await client.post("/api/accounts", json=CHECKING)
        await client.post(
            "/api/accounts",
            json={"name": "Cash Wallet", "type": "cash", "currency": "USD"},
        )
        resp = await client.get("/api/accounts", params={"type": "cash"})
        assert resp.status_code == 200
        accounts = resp.json()
        assert all(a["type"] == "cash" for a in accounts)
        assert len(accounts) == 1

    async def test_filter_by_is_active(self, client: AsyncClient) -> None:
        await client.post("/api/accounts", json=CHECKING)
        resp = await client.post("/api/accounts", json=SAVINGS)
        acct_id = resp.json()["id"]
        await client.delete(f"/api/accounts/{acct_id}")

        resp = await client.get(
            "/api/accounts", params={"is_active": "true"}
        )
        assert resp.status_code == 200
        assert all(a["is_active"] for a in resp.json())

        resp = await client.get(
            "/api/accounts", params={"is_active": "false"}
        )
        assert resp.status_code == 200
        assert all(not a["is_active"] for a in resp.json())

    async def test_filter_invalid_type_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(
            "/api/accounts", params={"type": "nonexistent"}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/accounts/{id}
# ---------------------------------------------------------------------------


class TestGetAccount:
    async def test_get_by_id(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.get(f"/api/accounts/{acct_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Checking"

    async def test_get_nonexistent_returns_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(f"/api/accounts/{NONEXISTENT_ID}")
        assert resp.status_code == 404

    async def test_get_invalid_id_format_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/accounts/not-an-objectid")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/accounts/{id} — RFC 6902 JSON Patch — happy path
# ---------------------------------------------------------------------------


class TestPatchAccount:
    async def test_replace_name(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/name", "value": "Primary"}],
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Primary"

    async def test_replace_balance(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/balance", "value": "999.99"}],
        )
        assert resp.status_code == 200
        assert Decimal(resp.json()["balance"]) == Decimal("999.99")

    async def test_replace_preserves_unpatched_fields(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post(
            "/api/accounts",
            json={
                "name": "Original",
                "type": "bank_account",
                "currency": "EUR",
                "initial_balance": "100",
            },
        )
        acct_id = create_resp.json()["id"]

        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/name", "value": "Renamed"}],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Renamed"
        assert body["currency"] == "EUR"
        assert Decimal(body["initial_balance"]) == Decimal("100")
        assert body["type"] == "bank_account"

    async def test_replace_multiple_fields(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [
                {"op": "replace", "path": "/name", "value": "Updated"},
                {"op": "replace", "path": "/balance", "value": "42"},
            ],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Updated"
        assert Decimal(body["balance"]) == Decimal("42")

    async def test_test_op_passes(self, client: AsyncClient) -> None:
        """RFC 6902 'test' op — replace only if current value matches."""
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [
                {"op": "test", "path": "/name", "value": "Checking"},
                {"op": "replace", "path": "/name", "value": "Tested"},
            ],
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Tested"

    async def test_test_op_fails_returns_409(
        self, client: AsyncClient
    ) -> None:
        """RFC 6902 'test' op — 409 when current value doesn't match."""
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [
                {"op": "test", "path": "/name", "value": "Wrong Name"},
                {"op": "replace", "path": "/name", "value": "Nope"},
            ],
        )
        assert resp.status_code == 409

    async def test_also_accepts_application_json(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/accounts/{acct_id}",
            json=[
                {"op": "replace", "path": "/name", "value": "Via JSON"},
            ],
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Via JSON"

    async def test_patch_nonexistent_returns_404(
        self, client: AsyncClient
    ) -> None:
        resp = await _json_patch(
            client,
            f"/api/accounts/{NONEXISTENT_ID}",
            [{"op": "replace", "path": "/name", "value": "X"}],
        )
        assert resp.status_code == 404

    async def test_patch_duplicate_name_returns_409(
        self, client: AsyncClient
    ) -> None:
        await client.post("/api/accounts", json=CHECKING)
        resp2 = await client.post("/api/accounts", json=SAVINGS)
        acct_id = resp2.json()["id"]

        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/name", "value": "Checking"}],
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /api/accounts/{id} — validation / invalid input
# ---------------------------------------------------------------------------


class TestPatchAccountValidation:
    async def test_empty_patch_array_returns_422(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client, f"/api/accounts/{acct_id}", []
        )
        assert resp.status_code == 422

    async def test_currency_not_patchable_returns_422(
        self, client: AsyncClient
    ) -> None:
        """Currency is immutable after creation."""
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/currency", "value": "EUR"}],
        )
        assert resp.status_code == 422
        assert "not patchable" in resp.json()["detail"].lower()

    async def test_invalid_balance_type_returns_422(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/balance", "value": "abc"}],
        )
        assert resp.status_code == 422

    async def test_malformed_json_returns_422(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/accounts/{acct_id}",
            content=b"not json",
            headers={"Content-Type": _JSON_PATCH},
        )
        assert resp.status_code == 422

    async def test_object_body_instead_of_array_returns_422(
        self, client: AsyncClient
    ) -> None:
        """Patch document must be a JSON array, not an object."""
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/accounts/{acct_id}",
            content=b'{"name": "X"}',
            headers={"Content-Type": _JSON_PATCH},
        )
        assert resp.status_code == 422

    async def test_non_patchable_field_returns_422(
        self, client: AsyncClient
    ) -> None:
        """Cannot patch owner_id, type, or other immutable fields."""
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"op": "replace", "path": "/owner_id", "value": "x"}],
        )
        assert resp.status_code == 422

    async def test_invalid_id_format_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await _json_patch(
            client,
            "/api/accounts/not-valid",
            [{"op": "replace", "path": "/name", "value": "X"}],
        )
        assert resp.status_code == 422

    async def test_unsupported_content_type_returns_415(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.patch(
            f"/api/accounts/{acct_id}",
            content=b'[{"op": "replace", "path": "/name", "value": "X"}]',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    async def test_missing_op_field_returns_422(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await _json_patch(
            client,
            f"/api/accounts/{acct_id}",
            [{"path": "/name", "value": "X"}],
        )
        assert resp.status_code == 422

    async def test_put_method_not_allowed(
        self, client: AsyncClient
    ) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.put(
            f"/api/accounts/{acct_id}", json={"name": "X"}
        )
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# DELETE /api/accounts/{id}
# ---------------------------------------------------------------------------


class TestDeleteAccount:
    async def test_soft_delete(self, client: AsyncClient) -> None:
        create_resp = await client.post("/api/accounts", json=CHECKING)
        acct_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/accounts/{acct_id}")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        get_resp = await client.get(f"/api/accounts/{acct_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["is_active"] is False

    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.delete(f"/api/accounts/{NONEXISTENT_ID}")
        assert resp.status_code == 404

    async def test_delete_invalid_id_format_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.delete("/api/accounts/not-valid")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------


class TestApiKeyAuth:
    async def test_api_key_works_for_accounts(
        self, client: AsyncClient
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://test"
        ) as http:
            resp = await http.get(
                "/api/accounts",
                headers={"X-API-Key": ADMIN_API_KEY},
            )
            assert resp.status_code == 200
