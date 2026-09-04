"""CRM workspace HTTP API integration tests - contacts, activities, notes, timeline.

End-to-end coverage of the CRM workspace over the FastAPI app:

  - contacts: create (anchored to a customer), get/patch, soft-deactivate,
    identity validation, two-tenant isolation;
  - activities: create anchored to any CRM entity, list by anchor + status
    filter, update, complete, delete;
  - notes: create/list/patch/delete, two-tenant isolation;
  - the MERGED relationship timeline (DB-layer UNION): lead.created +
    lead.qualified lifecycle events, an activity + a note appearing alongside
    them, and an order creation surfacing on the CUSTOMER's timeline
    (constraint: order events anchor to the customer, never an order entity);
  - the CRM overview (real aggregates only) and server-side search;
  - permission enforcement (401/403) on the workspace endpoints.

The suite skips when Postgres is unavailable (tests/integration/conftest.py).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest
from jose import jwt
from sqlalchemy import text

from core.core.config import settings
from core.core.permissions import (
    ERP_CRM_READ,
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
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_CRM = "/api/v1/crm"
_LEADS_URL = f"{_CRM}/leads"
_CUSTOMERS_URL = f"{_CRM}/customers"
_CONTACTS_URL = f"{_CRM}/contacts"
_ACTIVITIES_URL = f"{_CRM}/activities"
_NOTES_URL = f"{_CRM}/notes"
_TIMELINE_URL = f"{_CRM}/timeline"
_OVERVIEW_URL = f"{_CRM}/overview"
_SEARCH_URL = f"{_CRM}/search"

_ORDERS_URL = "/api/v1/sales/orders"
_PRODUCTS_URL = "/api/v1/inventory/products"

_SUBJECT_FULL = str(uuid.uuid4())
_SUBJECT_GLOBEX = str(uuid.uuid4())

_PERMISSIONS_FULL = [
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
    ERP_INVENTORY_ADJUST,
    ERP_INVENTORY_ADJUST_APPROVE,
    ERP_CRM_READ,
    ERP_CRM_WRITE,
    ERP_SALES_READ,
    ERP_SALES_WRITE,
    ERP_SALES_APPROVE,
    ERP_FINANCE_READ,
]


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


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


@pytest.fixture
async def rbac_world(integration_db: dict[str, str]) -> AsyncGenerator[dict[str, str], None]:
    """Seed identity users + core RBAC grants for the cross-module subject."""
    acme = uuid.UUID(integration_db["acme_id"])
    globex = uuid.UUID(integration_db["globex_id"])
    role_acme_full = uuid.uuid4()
    role_globex_read = uuid.uuid4()

    async with async_session_factory() as session:
        for sub, tid in ((_SUBJECT_FULL, acme), (_SUBJECT_GLOBEX, globex)):
            await session.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, password_hash, full_name) "
                    "VALUES (:id, :tid, :email, :hash, :name)"
                ),
                {
                    "id": uuid.UUID(sub),
                    "tid": tid,
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
                    name="api-workspace-full",
                    permissions=list(_PERMISSIONS_FULL),
                ),
                CoreRoleModel(
                    tenant_id=globex,
                    id=role_globex_read,
                    name="api-workspace-read",
                    permissions=[ERP_CRM_READ],
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
                    user_id=uuid.UUID(_SUBJECT_GLOBEX),
                    role_id=role_globex_read,
                ),
            ]
        )
        await session.commit()

    yield {"acme_id": integration_db["acme_id"], "globex_id": integration_db["globex_id"]}

    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM core_user_roles WHERE role_id IN (:r1, :r2)"),
            {"r1": role_acme_full, "r2": role_globex_read},
        )
        await session.execute(
            text("DELETE FROM core_roles WHERE id IN (:r1, :r2)"),
            {"r1": role_acme_full, "r2": role_globex_read},
        )
        await session.execute(
            text("DELETE FROM users WHERE id IN (:u1, :u2)"),
            {"u1": uuid.UUID(_SUBJECT_FULL), "u2": uuid.UUID(_SUBJECT_GLOBEX)},
        )
        await session.commit()


@pytest.fixture
def rbac_tokens(rbac_world: dict[str, str], rsa_private_key: str) -> dict[str, str]:
    return {
        "full": _token_for(rsa_private_key, rbac_world["acme_id"], _SUBJECT_FULL),
        "globex": _token_for(rsa_private_key, rbac_world["globex_id"], _SUBJECT_GLOBEX),
    }


async def _create_customer(
    client: AsyncClient, headers: dict[str, str], *, name: str
) -> dict[str, Any]:
    response = await client.post(_CUSTOMERS_URL, json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _create_lead(
    client: AsyncClient, headers: dict[str, str], *, email: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"first_name": "Ada", "last_name": "Lovelace", "source": "web"}
    if email is not None:
        payload["email"] = email
    response = await client.post(_LEADS_URL, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _qualify_lead(
    client: AsyncClient, headers: dict[str, str], lead_id: str, **body: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{_LEADS_URL}/{lead_id}/qualify", json=body or None, headers=headers
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _create_activity(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    entity_type: str,
    entity_id: str,
    subject: str,
    **extra: Any,
) -> dict[str, Any]:
    response = await client.post(
        _ACTIVITIES_URL,
        json={
            "kind": "task",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "subject": subject,
            **extra,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _create_note(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    entity_type: str,
    entity_id: str,
    body: str,
) -> dict[str, Any]:
    response = await client.post(
        _NOTES_URL,
        json={"entity_type": entity_type, "entity_id": entity_id, "body": body},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def _timeline(
    client: AsyncClient, headers: dict[str, str], *, entity_type: str, entity_id: str
) -> list[dict[str, Any]]:
    response = await client.get(
        _TIMELINE_URL, params={"entity_type": entity_type, "entity_id": entity_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    return cast("list[dict[str, Any]]", response.json()["data"])


class TestContacts:
    async def test_create_contact_requires_existing_customer(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        response = await client.post(
            f"{_CUSTOMERS_URL}/{uuid.uuid4()}/contacts",
            json={"first_name": "Grace", "email": f"grace-{_suffix()}@example.com"},
            headers=headers,
        )
        assert response.status_code == 404, response.text

    async def test_contact_requires_an_identity(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        customer = await _create_customer(client, headers, name=f"Acme {_suffix()}")
        response = await client.post(
            f"{_CUSTOMERS_URL}/{customer['id']}/contacts",
            json={"is_primary": True},
            headers=headers,
        )
        assert response.status_code == 422, response.text

    async def test_create_get_and_patch_contact(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        customer = await _create_customer(client, headers, name=f"Babbage {_suffix()}")
        response = await client.post(
            f"{_CUSTOMERS_URL}/{customer['id']}/contacts",
            json={
                "first_name": "Charles",
                "last_name": "Babbage",
                "email": f"cb-{_suffix()}@analytical.eng",
                "job_title": "Inventor",
                "is_primary": True,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        contact = response.json()["data"]
        assert contact["customer_id"] == customer["id"]
        assert contact["is_primary"] is True
        assert contact["is_active"] is True

        response = await client.get(f"{_CONTACTS_URL}/{contact['id']}", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["email"] == contact["email"]

        response = await client.patch(
            f"{_CONTACTS_URL}/{contact['id']}",
            json={"job_title": "Analytical Engine Designer"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["job_title"] == "Analytical Engine Designer"

    async def test_deactivate_contact_hides_it_from_lists(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        customer = await _create_customer(client, headers, name=f"Turing {_suffix()}")
        response = await client.post(
            f"{_CUSTOMERS_URL}/{customer['id']}/contacts",
            json={"first_name": "Alan", "email": f"at-{_suffix()}@example.com"},
            headers=headers,
        )
        contact = response.json()["data"]

        response = await client.delete(f"{_CONTACTS_URL}/{contact['id']}", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["is_active"] is False

        listed = (
            await client.get(_CONTACTS_URL, params={"customer_id": customer["id"]}, headers=headers)
        ).json()
        assert all(item["id"] != contact["id"] for item in listed["data"])

    async def test_contacts_are_tenant_isolated(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        olympus = tenant_headers()
        customer = await _create_customer(client, olympus, name=f"Isolated {_suffix()}")
        response = await client.post(
            f"{_CUSTOMERS_URL}/{customer['id']}/contacts",
            json={"first_name": "Private", "email": f"priv-{_suffix()}@example.com"},
            headers=olympus,
        )
        contact = response.json()["data"]

        globex = tenant_headers("globex")
        listed = (await client.get(_CONTACTS_URL, headers=globex)).json()
        assert all(item["id"] != contact["id"] for item in listed["data"])
        response = await client.get(f"{_CONTACTS_URL}/{contact['id']}", headers=globex)
        assert response.status_code == 404, response.text


class TestActivities:
    async def test_create_activity_requires_anchor(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        response = await client.post(
            _ACTIVITIES_URL,
            json={
                "kind": "task",
                "entity_type": "lead",
                "entity_id": str(uuid.uuid4()),
                "subject": "Orphan task",
            },
            headers=headers,
        )
        assert response.status_code == 404, response.text

    async def test_activity_subject_is_required(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers)
        response = await client.post(
            _ACTIVITIES_URL,
            json={"kind": "task", "entity_type": "lead", "entity_id": lead["id"], "subject": ""},
            headers=headers,
        )
        assert response.status_code == 422, response.text

    async def test_create_list_complete_and_filter_activities(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers, email=f"fol-{_suffix()}@example.com")
        activity = await _create_activity(
            client,
            headers,
            entity_type="lead",
            entity_id=lead["id"],
            subject="Call the analyst",
            kind="call",
        )

        listed = (
            await client.get(
                _ACTIVITIES_URL,
                params={"entity_type": "lead", "entity_id": lead["id"]},
                headers=headers,
            )
        ).json()
        assert any(item["id"] == activity["id"] for item in listed["data"])
        assert listed["data"][0]["completed_at"] is None

        open_rows = (
            await client.get(_ACTIVITIES_URL, params={"status": "open"}, headers=headers)
        ).json()
        assert any(item["id"] == activity["id"] for item in open_rows["data"])

        response = await client.post(
            f"{_ACTIVITIES_URL}/{activity['id']}/complete", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["completed_at"] is not None

        open_rows = (
            await client.get(_ACTIVITIES_URL, params={"status": "open"}, headers=headers)
        ).json()
        assert all(item["id"] != activity["id"] for item in open_rows["data"])
        completed = (
            await client.get(_ACTIVITIES_URL, params={"status": "completed"}, headers=headers)
        ).json()
        assert any(item["id"] == activity["id"] for item in completed["data"])

    async def test_update_and_delete_activity(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers)
        activity = await _create_activity(
            client, headers, entity_type="lead", entity_id=lead["id"], subject="Initial subject"
        )

        response = await client.patch(
            f"{_ACTIVITIES_URL}/{activity['id']}",
            json={"subject": "Updated subject"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["subject"] == "Updated subject"

        response = await client.delete(f"{_ACTIVITIES_URL}/{activity['id']}", headers=headers)
        assert response.status_code == 200, response.text
        response = await client.get(f"{_ACTIVITIES_URL}/{activity['id']}", headers=headers)
        assert response.status_code == 404, response.text


class TestNotes:
    async def test_create_note_requires_anchor(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        response = await client.post(
            _NOTES_URL,
            json={"entity_type": "lead", "entity_id": str(uuid.uuid4()), "body": "Orphan note"},
            headers=headers,
        )
        assert response.status_code == 404, response.text

    async def test_create_get_list_patch_delete_note(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers)
        response = await client.post(
            _NOTES_URL,
            json={"entity_type": "lead", "entity_id": lead["id"], "body": "First touch"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        note = response.json()["data"]
        assert note["body"] == "First touch"
        assert note["author_id"] is not None

        listed = (
            await client.get(
                _NOTES_URL, params={"entity_type": "lead", "entity_id": lead["id"]}, headers=headers
            )
        ).json()
        assert any(item["id"] == note["id"] for item in listed["data"])

        response = await client.patch(
            f"{_NOTES_URL}/{note['id']}", json={"body": "Revised note"}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["body"] == "Revised note"

        response = await client.delete(f"{_NOTES_URL}/{note['id']}", headers=headers)
        assert response.status_code == 200, response.text
        response = await client.get(f"{_NOTES_URL}/{note['id']}", headers=headers)
        assert response.status_code == 404, response.text

    async def test_notes_are_tenant_isolated(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        olympus = tenant_headers()
        lead = await _create_lead(client, olympus)
        note = await _create_note(
            client, olympus, entity_type="lead", entity_id=lead["id"], body="Private"
        )

        globex = tenant_headers("globex")
        listed = (
            await client.get(
                _NOTES_URL, params={"entity_type": "lead", "entity_id": lead["id"]}, headers=globex
            )
        ).json()
        assert listed["data"] == []
        response = await client.get(f"{_NOTES_URL}/{note['id']}", headers=globex)
        assert response.status_code == 404, response.text


class TestTimeline:
    async def test_lead_lifecycle_events_appear(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers, email=f"tl-{_suffix()}@example.com")
        await _qualify_lead(client, headers, lead["id"])

        items = await _timeline(client, headers, entity_type="lead", entity_id=lead["id"])
        titles = [item["title"] for item in items]
        assert "Lead created" in titles
        assert "Lead qualified" in titles
        assert all(item["entity_type"] == "lead" for item in items)
        # Newest first.
        assert titles[0] == "Lead qualified"

    async def test_timeline_merges_activities_notes_and_events(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers, email=f"merge-{_suffix()}@example.com")
        await _create_activity(
            client,
            headers,
            entity_type="lead",
            entity_id=lead["id"],
            subject="Call to schedule demo",
        )
        await _create_note(
            client, headers, entity_type="lead", entity_id=lead["id"], body="Prefers email"
        )

        items = await _timeline(client, headers, entity_type="lead", entity_id=lead["id"])
        assert "Lead created" in [item["title"] for item in items]
        assert any(item["kind"] == "task" and item["body"] is None for item in items)
        assert any(item["source"] == "note" and item["body"] == "Prefers email" for item in items)
        # The union is one ordered list, sources interleaved by occurred_at.
        assert {item["source"] for item in items} >= {"event", "activity", "note"}

    async def test_timeline_requires_anchor(self, client: AsyncClient, tenant_headers: Any) -> None:
        headers = tenant_headers()
        response = await client.get(
            _TIMELINE_URL,
            params={"entity_type": "customer", "entity_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert response.status_code == 404, response.text

    async def test_timeline_is_tenant_isolated(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        olympus = tenant_headers()
        lead = await _create_lead(client, olympus)

        globex = tenant_headers("globex")
        response = await client.get(
            _TIMELINE_URL,
            params={"entity_type": "lead", "entity_id": lead["id"]},
            headers=globex,
        )
        assert response.status_code == 404, response.text


class TestOrderOnCustomerTimeline:
    """Constraint: an order-created event anchors to the CUSTOMER entity."""

    async def test_order_creation_lands_on_customer_timeline(
        self, client: AsyncClient, rbac_tokens: dict[str, str]
    ) -> None:
        headers = {"X-Tenant-Slug": "olympus", "Authorization": f"Bearer {rbac_tokens['full']}"}
        response = await client.post(
            _CUSTOMERS_URL, json={"name": f"Timeline Buyer {_suffix()}"}, headers=headers
        )
        assert response.status_code == 201, response.text
        customer = response.json()["data"]

        response = await client.post(
            _PRODUCTS_URL,
            headers=headers,
            json={
                "sku": f"SKU-{_suffix()}",
                "name": f"Product {_suffix()}",
                "reorder_point": "0",
                "cost_price": [5.0, "USD"],
                "sell_price": [19.99, "USD"],
            },
        )
        assert response.status_code == 200, response.text
        product = response.json()["data"]

        response = await client.post(
            _ORDERS_URL,
            headers=headers,
            json={
                "customer_id": customer["id"],
                "lines": [{"product_id": product["id"], "quantity": "1"}],
            },
        )
        assert response.status_code == 201, response.text
        order = response.json()["data"]

        items = await _timeline(client, headers, entity_type="customer", entity_id=customer["id"])
        assert any(
            item["source"] == "event" and item["title"] == f"Order {order['order_number']} created"
            for item in items
        )
        # The anchor is the customer - never an 'order' entity type.
        assert all(item["entity_type"] == "customer" for item in items)


class TestOverview:
    async def test_overview_reflects_real_data(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        lead = await _create_lead(client, headers, email=f"ov-{_suffix()}@example.com")
        opportunity = await _qualify_lead(
            client, headers, lead["id"], amount="10000.00", currency="USD", probability=80
        )
        await client.post(
            f"{_CRM}/opportunities/{opportunity['id']}/stage",
            json={"stage": "won"},
            headers=headers,
        )
        await _create_activity(
            client,
            headers,
            entity_type="customer",
            entity_id=(await client.get(_CUSTOMERS_URL, headers=headers)).json()["data"][0]["id"],
            subject="Onboarding kickoff",
        )

        response = await client.get(_OVERVIEW_URL, headers=headers)
        assert response.status_code == 200, response.text
        overview = response.json()["data"]

        # The qualified+won lead drove one customer and one won opportunity.
        assert overview["opportunities"]["won_count"] >= 1
        assert overview["opportunities"]["lost_count"] == 0
        assert overview["customers"]["total"] >= 1
        assert overview["customers"]["active"] >= 1
        assert overview["leads"]["total"] >= 1
        assert any(
            status["status"] == "qualified" and status["count"] >= 1
            for status in overview["leads"]["by_status"]
        )
        # Per-currency buckets never mix currencies.
        assert any(
            bucket["currency"] == "USD"
            for bucket in overview["opportunities"]["open_value"]
            + overview["opportunities"]["won_value"]
        )


class TestSearch:
    async def test_search_finds_leads_customers_and_contacts(
        self, client: AsyncClient, tenant_headers: Any
    ) -> None:
        headers = tenant_headers()
        tag = _suffix()
        lead = await _create_lead(client, headers, email=f"{tag}@search.test")
        customer = await _create_customer(client, headers, name=f"Search Corp {tag}")
        response = await client.post(
            f"{_CUSTOMERS_URL}/{customer['id']}/contacts",
            json={"first_name": "Scout", "email": f"{tag}-contact@search.test"},
            headers=headers,
        )
        contact = response.json()["data"]

        response = await client.get(_SEARCH_URL, params={"q": tag}, headers=headers)
        assert response.status_code == 200, response.text
        hits = response.json()["data"]
        hit_ids = {(hit["entity_type"], hit["entity_id"]) for hit in hits}
        assert ("lead", lead["id"]) in hit_ids
        assert ("customer", customer["id"]) in hit_ids
        assert ("contact", contact["id"]) in hit_ids

    async def test_search_type_filter(self, client: AsyncClient, tenant_headers: Any) -> None:
        headers = tenant_headers()
        tag = _suffix()
        await _create_lead(client, headers, email=f"{tag}-filtered@search.test")
        customer = await _create_customer(client, headers, name=f"Filtered Corp {tag}")

        response = await client.get(
            _SEARCH_URL, params={"q": tag, "type": "customer"}, headers=headers
        )
        assert response.status_code == 200, response.text
        hits = response.json()["data"]
        assert all(hit["entity_type"] == "customer" for hit in hits)
        assert any(hit["entity_id"] == customer["id"] for hit in hits)

    async def test_search_requires_query(self, client: AsyncClient, tenant_headers: Any) -> None:
        response = await client.get(_SEARCH_URL, params={"q": ""}, headers=tenant_headers())
        assert response.status_code == 422, response.text


class TestAuthorization:
    async def test_unprivileged_gets_403(self, client: AsyncClient, tenant_headers: Any) -> None:
        headers = tenant_headers(unprivileged=True)
        response = await client.get(_ACTIVITIES_URL, headers=headers)
        assert response.status_code == 403, response.text
        response = await client.post(
            _NOTES_URL,
            json={"entity_type": "lead", "entity_id": str(uuid.uuid4()), "body": "nope"},
            headers=headers,
        )
        assert response.status_code == 403, response.text

    async def test_missing_token_gets_401(self, client: AsyncClient) -> None:
        response = await client.get(_TIMELINE_URL, headers={"X-Tenant-Slug": "olympus"})
        assert response.status_code == 401, response.text
        assert response.json()["type"].endswith("/authentication-error")
