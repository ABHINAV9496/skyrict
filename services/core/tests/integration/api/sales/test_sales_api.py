"""Sales HTTP API integration tests — real Postgres, full app stack.

End-to-end coverage of CRM-BE-002 over the FastAPI app: the draft order
lifecycle (create with server-side totals, PATCH while draft), the
confirm/fulfil/cancel money moments with their DB-guarded state transitions,
credit-limit enforcement (fails to confirm, order stays draft with a FAILED
credit check), insufficient-stock rollback, replay idempotency, invoice
creation on fulfil (finance cross-module port), DB-resolved permission
enforcement (401/403), and two-tenant isolation. The suite skips when
Postgres is unavailable (see tests/integration/conftest.py).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest
from jose import jwt
from sqlalchemy import select, text

from core.core.config import settings
from core.core.permissions import (
    ERP_CRM_WRITE,
    ERP_FINANCE_READ,
    ERP_INVENTORY_ADJUST,
    ERP_INVENTORY_ADJUST_APPROVE,
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
    ERP_SALES_APPROVE,
    ERP_SALES_READ,
    ERP_SALES_WRITE,
)
from core.db.session import async_session_factory
from core.features.audit.models.audit_log import AuditLogModel
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_ORDERS_URL = "/api/v1/sales/orders"
_PRODUCTS_URL = "/api/v1/inventory/products"
_WAREHOUSES_URL = "/api/v1/inventory/warehouses"
_ADJUSTMENTS_URL = "/api/v1/inventory/stock/adjustments"
_STOCK_URL = "/api/v1/inventory/stock"
_INVOICES_URL = "/api/v1/finance/invoices"

_SUBJECT_FULL = str(uuid.uuid4())
_SUBJECT_READONLY = str(uuid.uuid4())
_SUBJECT_GLOBEX = str(uuid.uuid4())

_PERMISSIONS_FULL = [
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
    ERP_INVENTORY_ADJUST,
    ERP_INVENTORY_ADJUST_APPROVE,
    ERP_CRM_WRITE,
    ERP_FINANCE_READ,
    ERP_SALES_READ,
    ERP_SALES_WRITE,
    ERP_SALES_APPROVE,
]


def _token_for(rsa_private_key: str, tenant_id: str, subject: str) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now - 10,
        "exp": now + 300,
        "type": "access",
    }
    return jwt.encode(payload, rsa_private_key, algorithm="RS256")


def _auth(slug: str, token: str) -> dict[str, str]:
    return {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"}


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture
async def rbac_world(integration_db: dict[str, str]) -> AsyncGenerator[dict[str, str], None]:
    """Seed identity users + core RBAC grants for the test subjects."""
    acme = uuid.UUID(integration_db["acme_id"])
    globex = uuid.UUID(integration_db["globex_id"])

    role_acme_full = uuid.uuid4()
    role_acme_read = uuid.uuid4()
    role_globex_read = uuid.uuid4()

    async with async_session_factory() as session:
        for sub in (_SUBJECT_FULL, _SUBJECT_READONLY, _SUBJECT_GLOBEX):
            await session.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, password_hash, full_name) "
                    "VALUES (:id, :tid, :email, :hash, :name)"
                ),
                {
                    "id": uuid.UUID(sub),
                    "tid": acme if sub != _SUBJECT_GLOBEX else globex,
                    "email": f"{sub}@skyrict.integration.test",
                    "hash": "not-a-real-hash",
                    "name": sub[:8],
                },
            )
        session.add_all(
            [
                CoreRoleModel(
                    tenant_id=acme,
                    id=role_acme_full,
                    name="api-sales-full",
                    permissions=list(_PERMISSIONS_FULL),
                ),
                CoreRoleModel(
                    tenant_id=acme,
                    id=role_acme_read,
                    name="api-sales-readonly",
                    permissions=[ERP_SALES_READ],
                ),
                CoreRoleModel(
                    tenant_id=globex,
                    id=role_globex_read,
                    name="api-sales-read",
                    permissions=[ERP_SALES_READ],
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                CoreUserRoleModel(
                    tenant_id=acme,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_SUBJECT_FULL),
                    role_id=role_acme_full,
                ),
                CoreUserRoleModel(
                    tenant_id=acme,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_SUBJECT_READONLY),
                    role_id=role_acme_read,  # read-only: confirm must 403
                ),
                CoreUserRoleModel(
                    tenant_id=globex,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_SUBJECT_GLOBEX),
                    role_id=role_globex_read,
                ),
            ]
        )
        # The fulfilment invoice posts against the tenant's standard Revenue
        # account (finance resolves code "4000"); seed it like finance's own
        # seeders do so the cross-module port works in isolation.
        for tid in (acme, globex):
            await session.execute(
                text(
                    "INSERT INTO erp_chart_of_accounts (tenant_id, id, code, name, account_type) "
                    "VALUES (:tid, :id, '4000', 'Revenue', 'revenue') "
                    "ON CONFLICT (tenant_id, code) DO NOTHING"
                ),
                {"tid": tid, "id": uuid.uuid4()},
            )
        await session.commit()

    yield {"acme_id": integration_db["acme_id"], "globex_id": integration_db["globex_id"]}

    role_ids = (role_acme_full, role_acme_read, role_globex_read)
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM core_user_roles WHERE role_id IN (:r1, :r2, :r3)"),
            {"r1": role_ids[0], "r2": role_ids[1], "r3": role_ids[2]},
        )
        await session.execute(
            text("DELETE FROM core_roles WHERE id IN (:r1, :r2, :r3)"),
            {"r1": role_ids[0], "r2": role_ids[1], "r3": role_ids[2]},
        )
        await session.execute(
            text("DELETE FROM users WHERE id IN (:u1, :u2, :u3)"),
            {
                "u1": uuid.UUID(_SUBJECT_FULL),
                "u2": uuid.UUID(_SUBJECT_READONLY),
                "u3": uuid.UUID(_SUBJECT_GLOBEX),
            },
        )
        await session.commit()


@pytest.fixture
def rbac_tokens(rbac_world: dict[str, str], rsa_private_key: str) -> dict[str, str]:
    return {
        "full": _token_for(rsa_private_key, rbac_world["acme_id"], _SUBJECT_FULL),
        "readonly": _token_for(rsa_private_key, rbac_world["acme_id"], _SUBJECT_READONLY),
        "globex": _token_for(rsa_private_key, rbac_world["globex_id"], _SUBJECT_GLOBEX),
    }


async def _create_customer(
    client: AsyncClient, headers: dict[str, str], *, name: str, credit_limit: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if credit_limit is not None:
        body["credit_limit"] = credit_limit
    response = await client.post("/api/v1/crm/customers", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _create_product(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    sku: str,
    sell_price: str = "19.99",
) -> dict[str, Any]:
    response = await client.post(
        _PRODUCTS_URL,
        headers=headers,
        json={
            "sku": sku,
            "name": f"Product {sku}",
            "reorder_point": "0",
            "cost_price": [12.5, "USD"],
            "sell_price": [sell_price, "USD"],
        },
    )
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _create_warehouse(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post(
        _WAREHOUSES_URL, headers=headers, json={"name": f"WH-{_suffix()}", "location": "A1"}
    )
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _adjust(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    product_id: str,
    warehouse_id: str,
    qty: int,
    ref_id: str,
) -> None:
    response = await client.post(
        _ADJUSTMENTS_URL,
        headers=headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "qty": qty,
            "reason": "integration-test",
            "ref_id": ref_id,
        },
    )
    assert response.status_code == 201, response.text


async def _create_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    customer_id: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    response = await client.post(
        _ORDERS_URL,
        headers=headers,
        json={"customer_id": customer_id, "lines": lines},
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _get_order(client: AsyncClient, headers: dict[str, str], order_id: str) -> dict[str, Any]:
    response = await client.get(f"{_ORDERS_URL}/{order_id}", headers=headers)
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _setup_world(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    """Customer + product + warehouse + stock for order flows."""
    customer = await _create_customer(client, headers, name=f"Buyer {_suffix()}")
    product = await _create_product(client, headers, sku=f"SKU-{_suffix()}")
    warehouse = await _create_warehouse(client, headers)
    await _adjust(
        client,
        headers,
        product_id=product["id"],
        warehouse_id=warehouse["id"],
        qty=100,
        ref_id=f"setup-{_suffix()}",
    )
    return {
        "customer_id": customer["id"],
        "product_id": product["id"],
        "warehouse_id": warehouse["id"],
    }


class TestDraftLifecycle:
    async def test_create_draft_order_derives_totals(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)

        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "3"}],
        )
        assert order["status"] == "draft"
        assert order["credit_check"] == "pending"
        assert order["subtotal"] == "59.9700"
        assert order["discount"] == "0.0000"
        assert order["tax"] == "0.0000"
        assert order["total"] == "59.9700"
        assert order["currency"] == "USD"
        assert order["order_number"].startswith("SO-")
        assert order["confirmed_at"] is None

    async def test_update_draft_order_recomputes_totals(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )
        assert order["total"] == "19.9900"

        response = await client.patch(
            f"{_ORDERS_URL}/{order['id']}",
            headers=headers,
            json={"lines": [{"product_id": world["product_id"], "quantity": "5"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] == "99.9500"

    async def test_missing_customer_404(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        response = await client.post(
            _ORDERS_URL,
            headers=headers,
            json={
                "customer_id": str(uuid.uuid4()),
                "lines": [{"product_id": world["product_id"], "quantity": "1"}],
            },
        )
        assert response.status_code == 404, response.text

    async def test_deactivated_customer_cannot_order(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        customer = await _create_customer(client, headers, name=f"Gone {_suffix()}")
        response = await client.delete(f"/api/v1/crm/customers/{customer['id']}", headers=headers)
        assert response.status_code == 200, response.text

        product = await _create_product(client, headers, sku=f"SKU-{_suffix()}")
        response = await client.post(
            _ORDERS_URL,
            headers=headers,
            json={
                "customer_id": customer["id"],
                "lines": [{"product_id": product["id"], "quantity": "1"}],
            },
        )
        assert response.status_code == 422, response.text


class TestConfirm:
    async def test_confirm_reserves_stock(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "3"}],
        )

        response = await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        assert response.status_code == 200, response.text
        confirmed = response.json()["data"]
        assert confirmed["status"] == "confirmed"
        assert confirmed["credit_check"] == "passed"
        assert confirmed["confirmed_at"] is not None

        stock = (
            await client.get(
                _STOCK_URL,
                headers=headers,
                params={"product_id": world["product_id"], "warehouse_id": world["warehouse_id"]},
            )
        ).json()["data"]
        assert stock[0]["qty_reserved"] == "3.0000"

    async def test_confirm_replay_is_idempotent(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )

        first = await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        second = await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        assert first.status_code == second.status_code == 200
        assert second.json()["data"]["id"] == order["id"]
        assert second.json()["data"]["status"] == "confirmed"

    async def test_credit_limit_exceeded_keeps_draft(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        customer = await _create_customer(
            client, headers, name=f"Tight {_suffix()}", credit_limit="50.00"
        )
        product = await _create_product(client, headers, sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, headers)
        await _adjust(
            client,
            headers,
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=100,
            ref_id=f"setup-{_suffix()}",
        )
        order = await _create_order(
            client,
            headers,
            customer_id=customer["id"],
            lines=[{"product_id": product["id"], "quantity": "3"}],  # 59.97 > 50.00
        )

        response = await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/credit-limit-exceeded")

        after = await _get_order(client, headers, order["id"])
        assert after["status"] == "draft"
        assert after["credit_check"] == "failed"

        # Retry after raising the limit succeeds (the failure is not terminal).
        response = await client.patch(
            f"/api/v1/crm/customers/{customer['id']}",
            headers=headers,
            json={"credit_limit": "100.00"},
        )
        assert response.status_code == 200, response.text
        response = await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        assert response.status_code == 200, response.text

    async def test_insufficient_stock_rolls_back(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        customer = await _create_customer(client, headers, name=f"Needy {_suffix()}")
        product = await _create_product(client, headers, sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, headers)
        await _adjust(
            client,
            headers,
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=1,
            ref_id=f"setup-{_suffix()}",
        )
        order = await _create_order(
            client,
            headers,
            customer_id=customer["id"],
            lines=[{"product_id": product["id"], "quantity": "2"}],
        )

        response = await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        assert response.status_code == 409, response.text

        after = await _get_order(client, headers, order["id"])
        assert after["status"] == "draft"


class TestFulfil:
    async def test_fulfil_creates_invoice(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "2"}],
        )
        assert (
            await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)
        ).status_code == 200

        response = await client.post(f"{_ORDERS_URL}/{order['id']}/fulfil", headers=headers)
        assert response.status_code == 200, response.text
        fulfilled = response.json()["data"]
        assert fulfilled["status"] == "fulfilled"

        invoices = (
            await client.get(_INVOICES_URL, headers=headers, params={"page_size": 20})
        ).json()["data"]
        assert any(inv["customer_id"] == world["customer_id"] for inv in invoices)

    async def test_fulfil_requires_confirmed_order(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )
        response = await client.post(f"{_ORDERS_URL}/{order['id']}/fulfil", headers=headers)
        assert response.status_code == 409, response.text


class TestCancel:
    async def test_cancel_releases_stock(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "4"}],
        )
        await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)

        response = await client.post(f"{_ORDERS_URL}/{order['id']}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "cancelled"

        stock = (
            await client.get(
                _STOCK_URL,
                headers=headers,
                params={"product_id": world["product_id"], "warehouse_id": world["warehouse_id"]},
            )
        ).json()["data"]
        assert stock[0]["qty_reserved"] == "0.0000"

    async def test_cancel_replay_is_idempotent(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )
        first = await client.post(f"{_ORDERS_URL}/{order['id']}/cancel", headers=headers)
        second = await client.post(f"{_ORDERS_URL}/{order['id']}/cancel", headers=headers)
        assert first.status_code == second.status_code == 200
        assert second.json()["data"]["status"] == "cancelled"


class TestAuthorization:
    async def test_readonly_cannot_confirm(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )

        readonly_headers = _auth("olympus", rbac_tokens["readonly"])
        response = await client.get(_ORDERS_URL, headers=readonly_headers)
        assert response.status_code == 200, response.text
        response = await client.post(
            f"{_ORDERS_URL}/{order['id']}/confirm", headers=readonly_headers
        )
        assert response.status_code == 403, response.text

    async def test_missing_token_gets_401(self, client: AsyncClient) -> None:
        # Tenant context present, no Authorization header → route-level auth.
        response = await client.get(_ORDERS_URL, headers={"X-Tenant-Slug": "olympus"})
        assert response.status_code == 401, response.text
        assert response.json()["type"].endswith("/authentication-error")


class TestTenantIsolation:
    async def test_globex_does_not_see_olympus_orders(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        olympus = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, olympus)
        order = await _create_order(
            client,
            olympus,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )

        globex = _auth("globex", rbac_tokens["globex"])
        response = await client.get(_ORDERS_URL, headers=globex)
        assert response.status_code == 200, response.text
        assert response.json()["data"] == []

        response = await client.get(f"{_ORDERS_URL}/{order['id']}", headers=globex)
        assert response.status_code == 404, response.text


class TestAuditTrail:
    async def test_confirm_writes_audit_row(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = _auth("olympus", rbac_tokens["full"])
        world = await _setup_world(client, headers)
        order = await _create_order(
            client,
            headers,
            customer_id=world["customer_id"],
            lines=[{"product_id": world["product_id"], "quantity": "1"}],
        )
        await client.post(f"{_ORDERS_URL}/{order['id']}/confirm", headers=headers)

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    select(AuditLogModel).where(
                        AuditLogModel.target == f"sales_order:{order['id']}",
                        AuditLogModel.action == "sales.order.confirmed",
                    )
                )
            ).scalar_one_or_none()
        assert row is not None
        assert row.action == "sales.order.confirmed"
