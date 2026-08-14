"""Inventory HTTP API integration tests — real Postgres, full app stack.

End-to-end coverage of INV-BE-002 §8 over the FastAPI app: response envelopes
and pagination, DB-resolved permission enforcement (401/403), business-rule
errors (409/422), the above-threshold approval gate
(``erp.inventory.adjust.approve``), two-tenant isolation, and the audit trail.
The suite skips when Postgres is unavailable (see tests/integration/conftest.py).
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from jose import jwt
from sqlalchemy import select, text

from core.core.config import settings
from core.core.permissions import (
    ERP_INVENTORY_ADJUST,
    ERP_INVENTORY_ADJUST_APPROVE,
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
)
from core.db.session import async_session_factory
from core.features.audit.models.audit_log import AuditLogModel
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_SUBJECT_FULL = str(uuid.uuid4())
_SUBJECT_READONLY = str(uuid.uuid4())
_SUBJECT_ADJUSTER = str(uuid.uuid4())


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


def _auth_olympus(token: str) -> dict[str, str]:
    return {"X-Tenant-Slug": "olympus", "Authorization": f"Bearer {token}"}


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture
async def rbac_world(integration_db: dict[str, str]) -> AsyncGenerator[dict[str, str], None]:
    """Seed identity users + core RBAC grants for the test subjects."""
    acme = uuid.UUID(integration_db["acme_id"])
    globex = uuid.UUID(integration_db["globex_id"])

    role_acme_full = uuid.uuid4()
    role_acme_read = uuid.uuid4()
    role_acme_adjust = uuid.uuid4()
    role_globex_read = uuid.uuid4()

    async with async_session_factory() as session:
        for sub in (_SUBJECT_FULL, _SUBJECT_READONLY, _SUBJECT_ADJUSTER):
            await session.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, password_hash, full_name) "
                    "VALUES (:id, :tid, :email, :hash, :name)"
                ),
                {
                    "id": uuid.UUID(sub),
                    "tid": acme,
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
                    name="api-full",
                    permissions=[
                        ERP_INVENTORY_READ,
                        ERP_INVENTORY_WRITE,
                        ERP_INVENTORY_ADJUST,
                        ERP_INVENTORY_ADJUST_APPROVE,
                    ],
                ),
                CoreRoleModel(
                    tenant_id=acme,
                    id=role_acme_read,
                    name="api-read",
                    permissions=[ERP_INVENTORY_READ],
                ),
                CoreRoleModel(
                    tenant_id=acme,
                    id=role_acme_adjust,
                    name="api-adjust",
                    permissions=[ERP_INVENTORY_READ, ERP_INVENTORY_WRITE, ERP_INVENTORY_ADJUST],
                ),
                CoreRoleModel(
                    tenant_id=globex,
                    id=role_globex_read,
                    name="api-read",
                    permissions=[ERP_INVENTORY_READ],
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
                    tenant_id=globex,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_SUBJECT_FULL),
                    role_id=role_globex_read,
                ),
                CoreUserRoleModel(
                    tenant_id=acme,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_SUBJECT_READONLY),
                    role_id=role_acme_read,
                ),
                CoreUserRoleModel(
                    tenant_id=acme,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_SUBJECT_ADJUSTER),
                    role_id=role_acme_adjust,
                ),
            ]
        )
        await session.commit()

    yield {"acme_id": integration_db["acme_id"], "globex_id": integration_db["globex_id"]}

    role_ids = (role_acme_full, role_acme_read, role_acme_adjust, role_globex_read)
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM core_user_roles WHERE role_id IN (:r1, :r2, :r3, :r4)"),
            {"r1": role_ids[0], "r2": role_ids[1], "r3": role_ids[2], "r4": role_ids[3]},
        )
        await session.execute(
            text("DELETE FROM core_roles WHERE id IN (:r1, :r2, :r3, :r4)"),
            {"r1": role_ids[0], "r2": role_ids[1], "r3": role_ids[2], "r4": role_ids[3]},
        )
        await session.execute(
            text("DELETE FROM users WHERE id IN (:u1, :u2, :u3)"),
            {
                "u1": uuid.UUID(_SUBJECT_FULL),
                "u2": uuid.UUID(_SUBJECT_READONLY),
                "u3": uuid.UUID(_SUBJECT_ADJUSTER),
            },
        )
        await session.commit()


@pytest.fixture
def rbac_tokens(rbac_world: dict[str, str], rsa_private_key: str) -> dict[str, str]:
    return {
        "full": _token_for(rsa_private_key, rbac_world["acme_id"], _SUBJECT_FULL),
        "readonly": _token_for(rsa_private_key, rbac_world["acme_id"], _SUBJECT_READONLY),
        "adjuster": _token_for(rsa_private_key, rbac_world["acme_id"], _SUBJECT_ADJUSTER),
        "globex": _token_for(rsa_private_key, rbac_world["globex_id"], _SUBJECT_FULL),
    }


async def _create_product(
    client: AsyncClient,
    token: str,
    *,
    sku: str,
    name: str = "Widget",
    category: str | None = None,
    reorder: str | int = "0",
) -> dict[str, object]:
    body: dict[str, object] = {
        "sku": sku,
        "name": name,
        "reorder_point": reorder,
        "cost_price": [12.5, "USD"],
        "sell_price": [19.99, "USD"],
    }
    if category is not None:
        body["category"] = category
    response = await client.post(
        "/api/v1/inventory/products", headers=_auth_olympus(token), json=body
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _create_warehouse(client: AsyncClient, token: str, *, name: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/inventory/warehouses",
        headers=_auth_olympus(token),
        json={"name": name, "location": "A1"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _adjust(
    client: AsyncClient,
    token: str,
    *,
    product_id: str,
    warehouse_id: str,
    qty: int | str,
    ref_id: str,
) -> object:
    return await client.post(
        "/api/v1/inventory/stock/adjustments",
        headers=_auth_olympus(token),
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "qty": qty,
            "reason": "integration-test",
            "ref_id": ref_id,
        },
    )


class TestProducts:
    async def test_create_product_returns_envelope(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        assert product["id"]
        assert product["sku"].startswith("SKU-")
        assert product["is_active"] is True
        assert product["cost_price"] == ["12.5000", "USD"]
        assert product["sell_price"] == ["19.9900", "USD"]

    async def test_duplicate_sku_returns_409(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        sku = f"SKU-{_suffix()}"
        await _create_product(client, rbac_tokens["full"], sku=sku)

        response = await client.post(
            "/api/v1/inventory/products",
            headers=_auth_olympus(rbac_tokens["full"]),
            json={"sku": sku, "name": "Dup"},
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")
        assert response.json()["status"] == 409

    async def test_list_products_is_paginated(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        category = f"cat-{_suffix()}"
        for _i in range(3):
            await _create_product(
                client, rbac_tokens["full"], sku=f"SKU-{_suffix()}", category=category
            )

        page1 = await client.get(
            "/api/v1/inventory/products",
            headers=_auth_olympus(rbac_tokens["full"]),
            params={"category": category, "page": 1, "page_size": 2},
        )
        assert page1.status_code == 200
        body = page1.json()["data"]
        assert body["meta"]["total"] == 3
        assert body["meta"]["total_pages"] == 2
        assert len(body["data"]) == 2

        page2 = await client.get(
            "/api/v1/inventory/products",
            headers=_auth_olympus(rbac_tokens["full"]),
            params={"category": category, "page": 2, "page_size": 2},
        )
        assert page2.status_code == 200
        assert len(page2.json()["data"]["data"]) == 1


class TestWarehouses:
    async def test_create_and_list_warehouses(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        name = f"WH-{_suffix()}"
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=name)
        assert warehouse["id"]
        assert warehouse["name"] == name
        assert warehouse["location"] == "A1"

        response = await client.get(
            "/api/v1/inventory/warehouses",
            headers=_auth_olympus(rbac_tokens["full"]),
        )
        assert response.status_code == 200
        names = [w["name"] for w in response.json()["data"]["data"]]
        assert name in names


class TestStockFlows:
    async def test_receipt_adjustment_updates_levels_and_movements(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        ref = f"ADJ-{_suffix()}"

        response = await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=10,
            ref_id=ref,
        )
        assert response.status_code == 201, response.text
        assert response.json()["message"] == "Stock adjusted"
        movement = response.json()["data"]
        assert movement["ref_id"] == ref
        assert Decimal(movement["qty"]) == Decimal("10")

        levels = await client.get(
            "/api/v1/inventory/stock",
            headers=_auth_olympus(rbac_tokens["full"]),
            params={"product_id": product["id"], "warehouse_id": warehouse["id"]},
        )
        assert levels.status_code == 200
        level = levels.json()["data"]["data"][0]
        assert Decimal(level["qty_on_hand"]) == Decimal("10")
        assert Decimal(level["qty_reserved"]) == Decimal("0")

        movements = await client.get(
            "/api/v1/inventory/stock/movements",
            headers=_auth_olympus(rbac_tokens["full"]),
            params={"product_id": product["id"], "warehouse_id": warehouse["id"]},
        )
        assert movements.status_code == 200
        assert len(movements.json()["data"]["data"]) == 1
        assert movements.json()["data"]["data"][0]["ref_id"] == ref

    async def test_insufficient_stock_returns_409(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        response = await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=-5,
            ref_id=f"ADJ-{_suffix()}",
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")

    async def test_zero_qty_adjustment_returns_422(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        response = await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=0,
            ref_id=f"ADJ-{_suffix()}",
        )
        assert response.status_code == 422
        assert response.json()["type"].endswith("/validation-error")

    async def test_replay_of_adjustment_ref_returns_409(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        ref = f"ADJ-{_suffix()}"
        first = await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=2,
            ref_id=ref,
        )
        assert first.status_code == 201

        second = await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=2,
            ref_id=ref,
        )
        assert second.status_code == 409
        assert second.json()["type"].endswith("/conflict")

    async def test_atomic_transfer_moves_stock(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        src = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        dst = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=src["id"],
            qty=10,
            ref_id=f"ADJ-{_suffix()}",
        )

        response = await client.post(
            "/api/v1/inventory/stock/transfers",
            headers=_auth_olympus(rbac_tokens["full"]),
            json={
                "product_id": product["id"],
                "from_warehouse_id": src["id"],
                "to_warehouse_id": dst["id"],
                "qty": 4,
                "ref_id": f"TR-{_suffix()}",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()["data"]
        assert Decimal(body["from_movement"]["qty"]) == Decimal("-4")
        assert Decimal(body["to_movement"]["qty"]) == Decimal("4")
        assert body["from_movement"]["ref_id"] == body["to_movement"]["ref_id"]

        levels = await client.get(
            "/api/v1/inventory/stock",
            headers=_auth_olympus(rbac_tokens["full"]),
            params={"product_id": product["id"]},
        )
        by_warehouse = {row["warehouse_id"]: row for row in levels.json()["data"]["data"]}
        assert Decimal(by_warehouse[src["id"]]["qty_on_hand"]) == Decimal("6")
        assert Decimal(by_warehouse[dst["id"]]["qty_on_hand"]) == Decimal("4")

    async def test_transfer_to_same_warehouse_returns_422(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        response = await client.post(
            "/api/v1/inventory/stock/transfers",
            headers=_auth_olympus(rbac_tokens["full"]),
            json={
                "product_id": product["id"],
                "from_warehouse_id": warehouse["id"],
                "to_warehouse_id": warehouse["id"],
                "qty": 1,
                "ref_id": f"TR-{_suffix()}",
            },
        )
        assert response.status_code == 422
        assert response.json()["type"].endswith("/validation-error")

    async def test_low_stock_product_appears_in_alerts(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        sku = f"SKU-{_suffix()}"
        product = await _create_product(client, rbac_tokens["full"], sku=sku, reorder="5")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=4,
            ref_id=f"ADJ-{_suffix()}",
        )

        response = await client.get(
            "/api/v1/inventory/alerts",
            headers=_auth_olympus(rbac_tokens["full"]),
        )
        assert response.status_code == 200
        skus = [a["sku"] for a in response.json()["data"]["data"]]
        assert sku in skus


class TestApprovalGate:
    async def test_above_threshold_adjustment_needs_approve_permission(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        product = await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")
        warehouse = await _create_warehouse(client, rbac_tokens["full"], name=f"WH-{_suffix()}")
        ref = f"ADJ-{_suffix()}"

        # The adjuster has erp.inventory.adjust but NOT erp.inventory.adjust.approve.
        denied = await _adjust(
            client,
            rbac_tokens["adjuster"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=150,
            ref_id=ref,
        )
        assert denied.status_code == 403
        assert denied.json()["type"].endswith("/permission-denied")

        # The full user may approve above-threshold adjustments.
        approved = await _adjust(
            client,
            rbac_tokens["full"],
            product_id=product["id"],
            warehouse_id=warehouse["id"],
            qty=150,
            ref_id=ref,
        )
        assert approved.status_code == 201, approved.text


class TestPermissionEnforcement:
    async def test_missing_token_returns_401(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/inventory/products", headers={"X-Tenant-Slug": "olympus"}
        )
        assert response.status_code == 401
        assert response.json()["type"].endswith("/authentication-error")

    async def test_readonly_can_list_but_not_create(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        listing = await client.get(
            "/api/v1/inventory/products",
            headers=_auth_olympus(rbac_tokens["readonly"]),
        )
        assert listing.status_code == 200

        created = await client.post(
            "/api/v1/inventory/products",
            headers=_auth_olympus(rbac_tokens["readonly"]),
            json={"sku": f"SKU-{_suffix()}", "name": "Nope"},
        )
        assert created.status_code == 403
        assert created.json()["type"].endswith("/permission-denied")


class TestTenantIsolation:
    async def test_globex_does_not_see_acme_products(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        sku = f"SKU-{_suffix()}"
        await _create_product(client, rbac_tokens["full"], sku=sku)

        response = await client.get(
            "/api/v1/inventory/products",
            headers={
                "X-Tenant-Slug": "globex",
                "Authorization": f"Bearer {rbac_tokens['globex']}",
            },
        )
        assert response.status_code == 200
        skus = [p["sku"] for p in response.json()["data"]["data"]]
        assert sku not in skus

    async def test_globex_cannot_write_acme_data(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
    ) -> None:
        response = await client.post(
            "/api/v1/inventory/products",
            headers={
                "X-Tenant-Slug": "globex",
                "Authorization": f"Bearer {rbac_tokens['globex']}",
            },
            json={"sku": f"SKU-{_suffix()}", "name": "Cross"},
        )
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")


class TestAuditTrail:
    async def test_product_creation_is_audited(
        self,
        client: AsyncClient,
        rbac_tokens: dict[str, str],
        rbac_world: dict[str, str],
    ) -> None:
        await _create_product(client, rbac_tokens["full"], sku=f"SKU-{_suffix()}")

        async with async_session_factory() as session:
            stmt = select(AuditLogModel).where(
                AuditLogModel.tenant_id == uuid.UUID(rbac_world["acme_id"]),
                AuditLogModel.action == "inventory.product.created",
                AuditLogModel.actor_user_id == uuid.UUID(_SUBJECT_FULL),
            )
            rows = (await session.execute(stmt)).scalars().all()
        assert rows, "expected an inventory.product.created audit row for the subject"
