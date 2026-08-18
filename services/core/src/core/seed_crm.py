"""CRM demo-data seeding — 10+ rows per CRM entity for demo/local workspaces.

Optional development data: unlike ``core.seed`` (per-tenant defaults applied at
provisioning), this seeds representative CRM records so the workspace UI has
something to show — leads, opportunities, customers, contacts, activities,
notes, and the curated timeline events that power the relationship feed.

Design notes:

- **Idempotent by default**: if the tenant already has CRM customers the run
  is a no-op (logs counts, inserts nothing). ``--force`` clears the six CRM
  tables for the tenant first, then reseeds.
- **Timestamps are staggered** over the past ~90 days so the timeline reads as
  a real history (ordered ``occurred_at desc, id desc``) instead of one big
  insert-timestamp clump.
- **Cross-references are realistic**: qualified leads carry a ``lead_id`` on
  their opportunity; the won opportunity is promoted to a customer via
  ``source_opportunity_id``; activities/notes anchor to leads, opportunities,
  customers and contacts; ``order.created`` timeline events anchor to the
  related customer (per the SKY-45 constraint — never an ``order`` entity).
- **RLS**: seed connections run without a tenant context (like ``core.seed``),
  so inserts are bounded only by the role used to run the CLI. If the connect
  role is not the table owner you must set the ``app.current_tenant_id`` GUC.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, func, select, text

from core.db.session import async_session_factory
from core.domain.value_objects import (
    ActivityKind,
    CrmEntityType,
    CrmTimelineEventType,
    LeadStatus,
    OpportunityStage,
)
from core.features.crm.models.activity import ErpCrmActivityModel
from core.features.crm.models.contact import ErpCrmContactModel
from core.features.crm.models.customer import ErpCrmCustomerModel
from core.features.crm.models.lead import ErpCrmLeadModel
from core.features.crm.models.note import ErpCrmNoteModel
from core.features.crm.models.opportunity import ErpCrmOpportunityModel
from core.features.crm.models.timeline_event import ErpCrmTimelineEventModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("core.seed.crm")

# ---------------------------------------------------------------------------
# Demo dataset
# ---------------------------------------------------------------------------


def _ago(days: float, hours: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=days, hours=hours)


LEAD_ROWS: tuple[dict[str, object], ...] = (
    {
        "status": LeadStatus.NEW,
        "source": "website",
        "first_name": "Maya",
        "last_name": "Okonkwo",
        "email": "maya.okonkwo@brightline.io",
        "phone": "+1 415 555 0112",
        "company": "Brightline Analytics",
        "days_ago": 1.2,
    },
    {
        "status": LeadStatus.NEW,
        "source": "linkedin",
        "first_name": "Jonas",
        "last_name": "Weber",
        "email": "jonas.weber@kronfeld.de",
        "phone": "+49 89 555 0143",
        "company": "Kronfeld Bau",
        "days_ago": 2.5,
    },
    {
        "status": LeadStatus.CONTACTED,
        "source": "website",
        "first_name": "Priya",
        "last_name": "Nair",
        "email": "priya.nair@bluehorizon.co.in",
        "phone": "+91 22 555 0158",
        "company": "Blue Horizon Logistics",
        "days_ago": 4.0,
    },
    {
        "status": LeadStatus.CONTACTED,
        "source": "referral",
        "first_name": "Daniel",
        "last_name": "Reyes",
        "email": "daniel.reyes@mangrovetech.mx",
        "phone": "+52 55 555 0177",
        "company": "Mangrove Tech",
        "days_ago": 5.5,
    },
    {
        "status": LeadStatus.CONTACTED,
        "source": "event",
        "first_name": "Sofia",
        "last_name": "Mendes",
        "email": "sofia.mendes@atlanticap.pt",
        "phone": "+351 21 555 0190",
        "company": "Atlantica Partners",
        "days_ago": 7.0,
    },
    {
        "status": LeadStatus.CONTACTED,
        "source": "website",
        "first_name": "Tariq",
        "last_name": "Haddad",
        "email": "tariq.haddad@duneconsulting.ae",
        "phone": "+971 4 555 0125",
        "company": "Dune Consulting",
        "days_ago": 8.5,
    },
    {
        "status": LeadStatus.CONTACTED,
        "source": "ads",
        "first_name": "Emily",
        "last_name": "Carter",
        "email": "emily.carter@northstar-foods.co.uk",
        "phone": "+44 20 555 0162",
        "company": "Northstar Foods",
        "days_ago": 10.0,
    },
    {
        "status": LeadStatus.QUALIFIED,
        "source": "referral",
        "first_name": "Hannah",
        "last_name": "Kowalski",
        "email": "hannah.kowalski@cedarpeak.ca",
        "phone": "+1 604 555 0131",
        "company": "Cedar Peak Outdoor",
        "days_ago": 12.0,
    },
    {
        "status": LeadStatus.QUALIFIED,
        "source": "website",
        "first_name": "Marco",
        "last_name": "Rossi",
        "email": "marco.rossi@formagroup.it",
        "phone": "+39 02 555 0184",
        "company": "Forma Group",
        "days_ago": 14.0,
    },
    {
        "status": LeadStatus.DISQUALIFIED,
        "source": "ads",
        "first_name": "Katie",
        "last_name": "Zhang",
        "email": "katie.zhang@eastwood-retail.com.au",
        "phone": "+61 2 555 0153",
        "company": "Eastwood Retail",
        "days_ago": 9.0,
    },
    {
        "status": LeadStatus.DISQUALIFIED,
        "source": "event",
        "first_name": "Omar",
        "last_name": "Saleh",
        "email": "omar.saleh@mideast-machinery.eg",
        "phone": "+20 2 555 0119",
        "company": "Mideast Machinery",
        "days_ago": 16.0,
    },
    {
        "status": LeadStatus.CONTACTED,
        "source": "website",
        "first_name": "Lena",
        "last_name": "Vogt",
        "email": "lena.vogt@alpenlogistics.ch",
        "phone": "+41 44 555 0173",
        "company": "Alpen Logistics",
        "days_ago": 3.0,
    },
)

# Qualified leads become opportunities below (lead_id linkage).
_QUALIFIED_LEAD_COMPANIES = {"Cedar Peak Outdoor", "Forma Group"}

_OPPORTUNITY_ROWS: tuple[dict[str, object], ...] = (
    {
        "name": "Cedar Peak Outdoor — annual gear refresh",
        "from_company": "Cedar Peak Outdoor",
        "stage": OpportunityStage.QUALIFIED,
        "amount": "48000",
        "currency": "CAD",
        "probability": 40,
        "close_days": 45,
        "days_ago": 12.0,
    },
    {
        "name": "Forma Group — retail ERP rollout",
        "from_company": "Forma Group",
        "stage": OpportunityStage.NEGOTIATION,
        "amount": "156000",
        "currency": "EUR",
        "probability": 75,
        "close_days": 20,
        "days_ago": 14.0,
    },
    {
        "name": "Vesper Systems — inventory modules",
        "stage": OpportunityStage.PROSPECTING,
        "amount": None,
        "currency": None,
        "probability": 10,
        "close_days": 90,
        "days_ago": 2.0,
    },
    {
        "name": "Halcyon Media — multi-warehouse setup",
        "stage": OpportunityStage.PROSPECTING,
        "amount": "72000",
        "currency": "USD",
        "probability": 15,
        "close_days": 80,
        "days_ago": 3.5,
    },
    {
        "name": "Ironclad Marine — safety compliance suite",
        "stage": OpportunityStage.QUALIFIED,
        "amount": "39500",
        "currency": "USD",
        "probability": 45,
        "close_days": 60,
        "days_ago": 6.0,
    },
    {
        "name": "Sagehill Health — patient portal",
        "stage": OpportunityStage.PROPOSAL,
        "amount": "88000",
        "currency": "USD",
        "probability": 60,
        "close_days": 35,
        "days_ago": 9.0,
    },
    {
        "name": "Quicksilver Bank — audit automation",
        "stage": OpportunityStage.PROPOSAL,
        "amount": "240000",
        "currency": "USD",
        "probability": 55,
        "close_days": 40,
        "days_ago": 11.0,
    },
    {
        "name": "Zephyr Airlines — loyalty rebuild",
        "stage": OpportunityStage.NEGOTIATION,
        "amount": "310000",
        "currency": "USD",
        "probability": 70,
        "close_days": 25,
        "days_ago": 13.0,
    },
    {
        "name": "Commonwealth Glass — plant digitization",
        "stage": OpportunityStage.WON,
        "amount": "92000",
        "currency": "GBP",
        "probability": 100,
        "close_days": -30,
        "days_ago": 60.0,
    },
    {
        "name": "Meridian Consulting — analytics pilot",
        "stage": OpportunityStage.LOST,
        "amount": "15000",
        "currency": "USD",
        "probability": 0,
        "close_days": -12,
        "days_ago": 25.0,
        "lost_reason": "Budget redirected to headcount",
    },
    {
        "name": "Stonebridge Construction — field service",
        "stage": OpportunityStage.PROSPECTING,
        "amount": "64000",
        "currency": "USD",
        "probability": 20,
        "close_days": 70,
        "days_ago": 4.5,
    },
    {
        "name": "Harbor & Fenwick — legal document AI",
        "stage": OpportunityStage.QUALIFIED,
        "amount": "51000",
        "currency": "USD",
        "probability": 50,
        "close_days": 50,
        "days_ago": 8.0,
    },
)

_CUSTOMER_ROWS: tuple[dict[str, object], ...] = (
    {
        "code": "CUS-0001",
        "name": "Commonwealth Glass PLC",
        "email": "accounts@commonwealthglass.co.uk",
        "phone": "+44 121 555 0142",
        "credit_limit": "150000",
        "currency": "GBP",
        "source_opportunity": "Commonwealth Glass — plant digitization",
        "days_ago": 60.0,
    },
    {
        "code": "CUS-0002",
        "name": "Alder & Sons Distributors",
        "email": "ap@alderdistributors.com",
        "phone": "+1 206 555 0181",
        "credit_limit": "90000",
        "currency": "USD",
        "days_ago": 55.0,
    },
    {
        "code": "CUS-0003",
        "name": "Redpine Construction Co.",
        "email": "billing@redpine.com",
        "phone": "+1 303 555 0128",
        "credit_limit": "120000",
        "currency": "USD",
        "days_ago": 48.0,
    },
    {
        "code": "CUS-0004",
        "name": "Veridian Foods",
        "email": "finance@veridianfoods.com",
        "phone": "+1 212 555 0167",
        "credit_limit": "75000",
        "currency": "USD",
        "days_ago": 41.0,
    },
    {
        "code": "CUS-0005",
        "name": "Summit Outfitters GmbH",
        "email": "kontakt@summit-outfitters.de",
        "phone": "+49 40 555 0155",
        "credit_limit": "60000",
        "currency": "EUR",
        "days_ago": 33.0,
    },
    {
        "code": "CUS-0006",
        "name": "Oakhill Medical Group",
        "email": "purchasing@oakhill.health",
        "phone": "+1 615 555 0136",
        "credit_limit": "130000",
        "currency": "USD",
        "days_ago": 27.0,
    },
    {
        "code": "CUS-0007",
        "name": "Granite Bay Technologies",
        "email": "po@granitebaytech.com",
        "phone": "+1 408 555 0174",
        "credit_limit": None,
        "currency": None,
        "days_ago": 19.0,
    },
    {
        "code": "CUS-0008",
        "name": "Lakeshore Electronics",
        "email": "orders@lakeshoreelec.com",
        "phone": "+1 312 555 0122",
        "credit_limit": "85000",
        "currency": "USD",
        "days_ago": 14.0,
    },
    {
        "code": "CUS-0009",
        "name": "Pinnacle Group Asia",
        "email": "finance@pinnaclegroup.sg",
        "phone": "+65 6555 0189",
        "credit_limit": "110000",
        "currency": "SGD",
        "days_ago": 8.0,
    },
    {
        "code": "CUS-0010",
        "name": "Willow & Sage Retail",
        "email": "hello@willowandsage.ca",
        "phone": "+1 416 555 0160",
        "credit_limit": "40000",
        "currency": "CAD",
        "days_ago": 3.0,
    },
)

_CONTACT_ROWS: tuple[dict[str, object], ...] = (
    {
        "customer": 0,
        "first": "Oliver",
        "last": "Hartley",
        "email": "oliver.hartley@commonwealthglass.co.uk",
        "phone": "+44 121 555 0193",
        "title": "Procurement Director",
        "primary": True,
    },
    {
        "customer": 0,
        "first": "Amelia",
        "last": "Stone",
        "email": "amelia.stone@commonwealthglass.co.uk",
        "phone": "+44 121 555 0194",
        "title": "Finance Lead",
        "primary": False,
    },
    {
        "customer": 1,
        "first": "Caleb",
        "last": "Mercer",
        "email": "caleb.mercer@alderdistributors.com",
        "phone": "+1 206 555 0115",
        "title": "Operations Manager",
        "primary": True,
    },
    {
        "customer": 2,
        "first": "Grace",
        "last": "Lindqvist",
        "email": "grace.lindqvist@redpine.com",
        "phone": "+1 303 555 0186",
        "title": "VP Sales",
        "primary": True,
    },
    {
        "customer": 3,
        "first": "Nolan",
        "last": "Fisher",
        "email": "nolan.fisher@veridianfoods.com",
        "phone": "+1 212 555 0139",
        "title": "Head of Procurement",
        "primary": True,
    },
    {
        "customer": 4,
        "first": "Eva",
        "last": "Brandt",
        "email": "eva.brandt@summit-outfitters.de",
        "phone": "+49 40 555 0121",
        "title": "Chief Operating Officer",
        "primary": True,
    },
    {
        "customer": 5,
        "first": "Theo",
        "last": "Barnes",
        "email": "theo.barnes@oakhill.health",
        "phone": "+1 615 555 0148",
        "title": "IT Director",
        "primary": True,
    },
    {
        "customer": 6,
        "first": "Iris",
        "last": "Chambers",
        "email": "iris.chambers@granitebaytech.com",
        "phone": "+1 408 555 0165",
        "title": "Head of Engineering",
        "primary": True,
    },
    {
        "customer": 7,
        "first": "Milo",
        "last": "Granger",
        "email": "milo.granger@lakeshoreelec.com",
        "phone": "+1 312 555 0178",
        "title": "Purchasing Lead",
        "primary": True,
    },
    {
        "customer": 8,
        "first": "Aisha",
        "last": "Tan",
        "email": "aisha.tan@pinnaclegroup.sg",
        "phone": "+65 6555 0123",
        "title": "Finance Manager",
        "primary": True,
    },
    {
        "customer": 9,
        "first": "Henry",
        "last": "Windsor",
        "email": "henry.windsor@willowandsage.ca",
        "phone": "+1 416 555 0157",
        "title": "Founder",
        "primary": True,
    },
    {
        "customer": 3,
        "first": "Ruby",
        "last": "Delgado",
        "email": "ruby.delgado@veridianfoods.com",
        "phone": "+1 212 555 0168",
        "title": "Category Manager",
        "primary": False,
    },
    {
        "customer": 5,
        "first": "Jack",
        "last": "O'Connell",
        "email": "jack.oconnell@oakhill.health",
        "phone": "+1 615 555 0172",
        "title": "Facilities Lead",
        "primary": False,
    },
    {
        "customer": 2,
        "first": "Freya",
        "last": "Ashworth",
        "email": "freya.ashworth@redpine.com",
        "phone": "+1 303 555 0199",
        "title": "Project Coordinator",
        "primary": False,
    },
)

_ACTIVITY_ROWS: tuple[dict[str, object], ...] = (
    {
        "kind": ActivityKind.FOLLOW_UP,
        "anchor": ("lead", 0),
        "subject": "Demo call with Brightline",
        "description": "Walked through the product; they want a pricing sheet.",
        "due_days": 1,
        "completed": False,
    },
    {
        "kind": ActivityKind.CALL,
        "anchor": ("lead", 1),
        "subject": "Intro call — Kronfeld Bau",
        "description": "Discussed warehouse footprint and integration needs.",
        "due_days": -1,
        "completed": True,
    },
    {
        "kind": ActivityKind.EMAIL,
        "anchor": ("lead", 2),
        "subject": "Sent follow-up deck",
        "description": "Shared the logistics solution deck.",
        "due_days": -2,
        "completed": True,
    },
    {
        "kind": ActivityKind.TASK,
        "anchor": ("lead", 3),
        "subject": "Prepare proposal draft",
        "description": "Draft the scope for Mangrove Tech.",
        "due_days": 3,
        "completed": False,
    },
    {
        "kind": ActivityKind.MEETING,
        "anchor": ("lead", 4),
        "subject": "Discovery workshop",
        "description": "Requirements gathering for Atlantica.",
        "due_days": 5,
        "completed": False,
    },
    {
        "kind": ActivityKind.TASK,
        "anchor": ("lead", 11),
        "subject": "Send NDA for Alpen Logistics",
        "due_days": 2,
        "completed": False,
    },
    {
        "kind": ActivityKind.CALL,
        "anchor": ("opportunity", 0),
        "subject": "Quarterly review — Cedar Peak",
        "description": "Confirmed budget line for the gear refresh.",
        "due_days": -3,
        "completed": True,
    },
    {
        "kind": ActivityKind.FOLLOW_UP,
        "anchor": ("opportunity", 0),
        "subject": "Send revised contract",
        "due_days": 4,
        "completed": False,
    },
    {
        "kind": ActivityKind.MEETING,
        "anchor": ("opportunity", 1),
        "subject": "Negotiation session — Forma Group",
        "description": "Aligning on rollout timeline and support terms.",
        "due_days": 2,
        "completed": False,
    },
    {
        "kind": ActivityKind.EMAIL,
        "anchor": ("opportunity", 1),
        "subject": "Proposal v3 sent",
        "description": "Included volume discount and onboarding plan.",
        "due_days": -4,
        "completed": True,
    },
    {
        "kind": ActivityKind.TASK,
        "anchor": ("opportunity", 2),
        "subject": "Qualify Vesper Systems scope",
        "due_days": 7,
        "completed": False,
    },
    {
        "kind": ActivityKind.CALL,
        "anchor": ("opportunity", 4),
        "subject": "Solution demo — Ironclad",
        "description": "Safety compliance walkthrough.",
        "due_days": -2,
        "completed": True,
    },
    {
        "kind": ActivityKind.FOLLOW_UP,
        "anchor": ("opportunity", 5),
        "subject": "Answer Sagehill pricing questions",
        "due_days": 1,
        "completed": False,
    },
    {
        "kind": ActivityKind.MEETING,
        "anchor": ("opportunity", 6),
        "subject": "Quicksilver security review",
        "due_days": 6,
        "completed": False,
    },
    {
        "kind": ActivityKind.EMAIL,
        "anchor": ("opportunity", 7),
        "subject": "Zephyr — commercial terms sent",
        "due_days": -1,
        "completed": True,
    },
    {
        "kind": ActivityKind.CALL,
        "anchor": ("opportunity", 11),
        "subject": "Discovery — Harbor & Fenwick",
        "description": "Legal document AI scope call.",
        "due_days": 3,
        "completed": False,
    },
    {
        "kind": ActivityKind.FOLLOW_UP,
        "anchor": ("customer", 0),
        "subject": "Quarterly business review",
        "description": "Reviewing satisfaction and roadmap.",
        "due_days": -5,
        "completed": True,
    },
    {
        "kind": ActivityKind.EMAIL,
        "anchor": ("customer", 0),
        "subject": "Sent renewal notice",
        "due_days": 10,
        "completed": False,
    },
    {
        "kind": ActivityKind.CALL,
        "anchor": ("customer", 1),
        "subject": "Support call — Alder",
        "description": "Helped with the export template issue.",
        "due_days": -1,
        "completed": True,
    },
    {
        "kind": ActivityKind.TASK,
        "anchor": ("customer", 2),
        "subject": "Upload Redpine asset list",
        "due_days": 2,
        "completed": False,
    },
    {
        "kind": ActivityKind.MEETING,
        "anchor": ("customer", 5),
        "subject": "Oakhill training session",
        "description": "Train new staff on the system.",
        "due_days": 8,
        "completed": False,
    },
    {
        "kind": ActivityKind.FOLLOW_UP,
        "anchor": ("customer", 7),
        "subject": "Chase Lakeshore payment",
        "due_days": 0,
        "completed": False,
    },
    {
        "kind": ActivityKind.EMAIL,
        "anchor": ("contact", 4),
        "subject": "Veridian — onboarding email",
        "due_days": -1,
        "completed": True,
    },
    {
        "kind": ActivityKind.CALL,
        "anchor": ("customer", 9),
        "subject": "Welcome call — Willow & Sage",
        "description": "Walked through first steps.",
        "due_days": -1,
        "completed": True,
    },
)

_NOTE_ROWS: tuple[dict[str, object], ...] = (
    {
        "anchor": ("lead", 0),
        "body": "Maya mentioned they evaluate two vendors each year. Keep the pricing sheet concise.",
    },
    {"anchor": ("lead", 2), "body": "Prefers email over phone. Local timezone UTC+5:30."},
    {
        "anchor": ("lead", 7),
        "body": "Referred by Veridian Foods. Strong fit for the outdoor retail segment.",
    },
    {
        "anchor": ("opportunity", 0),
        "body": "Champion is Hannah at Cedar Peak — keeps the budget line visible internally.",
    },
    {
        "anchor": ("opportunity", 1),
        "body": "Forma is comparing with a local competitor; our onboarding speed is the differentiator.",
    },
    {
        "anchor": ("opportunity", 5),
        "body": "Sagehill needs a SOC 2 appendix in the proposal. Ask security to draft it.",
    },
    {
        "anchor": ("opportunity", 6),
        "body": "Quicksilver procurement cycle takes ~30 days after sign-off.",
    },
    {
        "anchor": ("customer", 0),
        "body": "Renewal due in the next quarter. Finance contact is Amelia Stone.",
    },
    {
        "anchor": ("customer", 1),
        "body": "Sensitive to price changes — grandfather rates if possible.",
    },
    {
        "anchor": ("customer", 5),
        "body": "Expanding to two new clinics next year; plan for extra seats.",
    },
    {
        "anchor": ("customer", 9),
        "body": "New account — prefer weekly check-ins during the first month.",
    },
    {"anchor": ("contact", 4), "body": "Nolan is the decision maker for Veridian procurement."},
)

# Order-created timeline events anchored to customers (constraint: never an
# ``order`` entity type).
_ORDER_EVENTS: tuple[dict[str, object], ...] = (
    {"customer": 0, "order": "ORD-1041", "total": "18250.00", "days_ago": 35.0},
    {"customer": 2, "order": "ORD-1047", "total": "9450.00", "days_ago": 21.0},
    {"customer": 5, "order": "ORD-1052", "total": "12780.00", "days_ago": 9.0},
)

# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _resolve_owner_id(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    """Pick the first active user of the tenant (shared identity schema)."""
    row = (
        await session.execute(
            text(
                "SELECT id FROM users "
                "WHERE tenant_id = :tenant_id AND is_active = true "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            {"tenant_id": tenant_id},
        )
    ).scalar_one_or_none()
    return row if row is None else uuid.UUID(str(row))


async def seed_crm_demo_data(tenant_id: uuid.UUID, *, force: bool = False) -> dict[str, int]:
    """Seed demo CRM data for one tenant. Idempotent unless ``force``."""
    async with async_session_factory() as session:
        if force:
            for model in (
                ErpCrmTimelineEventModel,
                ErpCrmNoteModel,
                ErpCrmActivityModel,
                ErpCrmContactModel,
                ErpCrmCustomerModel,
                ErpCrmOpportunityModel,
                ErpCrmLeadModel,
            ):
                await session.execute(
                    delete(model.__table__).where(model.__table__.c.tenant_id == tenant_id)  # type: ignore[arg-type]
                )
            await session.commit()
            logger.info("seed.crm.cleared", tenant_id=str(tenant_id))

        existing_customers = (
            await session.execute(
                select(func.count())
                .select_from(ErpCrmCustomerModel)
                .where(ErpCrmCustomerModel.tenant_id == tenant_id)
            )
        ).scalar_one()
        if existing_customers and not force:
            logger.info(
                "seed.crm.skip",
                tenant_id=str(tenant_id),
                reason="tenant already has CRM customers",
            )
            return {"skipped": int(existing_customers)}

        owner_id = await _resolve_owner_id(session, tenant_id)

        # --- Leads ---------------------------------------------------------
        lead_ids: list[uuid.UUID] = []
        for row in LEAD_ROWS:
            lead = ErpCrmLeadModel(
                tenant_id=tenant_id,
                status=row["status"],
                source=row["source"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                phone=row["phone"],
                company=row["company"],
                owner_id=owner_id,
                created_at=_ago(float(str(row["days_ago"]))),
            )
            session.add(lead)
            await session.flush()
            lead_ids.append(lead.id)

        # --- Opportunities -------------------------------------------------
        opportunity_ids: list[uuid.UUID] = []
        opportunity_by_name: dict[str, uuid.UUID] = {}
        qualified_by_company: dict[str, uuid.UUID] = {}
        for row in _OPPORTUNITY_ROWS:
            from_company = row.get("from_company")
            linked_lead: uuid.UUID | None = None
            if from_company:
                lead_index = next(
                    (i for i, lead in enumerate(LEAD_ROWS) if lead["company"] == from_company),
                    None,
                )
                if lead_index is not None:
                    linked_lead = lead_ids[lead_index]
                    qualified_by_company[str(from_company)] = lead_ids[lead_index]

            stage = row["stage"]
            stage_changed_days = float(str(row["days_ago"]))
            won_at = _ago(float(str(row["close_days"]))) if stage == OpportunityStage.WON else None
            lost_at = (
                _ago(float(str(row["close_days"]))) if stage == OpportunityStage.LOST else None
            )

            amount_raw = row.get("amount")
            opportunity = ErpCrmOpportunityModel(
                tenant_id=tenant_id,
                name=row["name"],
                lead_id=linked_lead,
                stage=stage,
                amount=Decimal(str(amount_raw)) if amount_raw is not None else None,
                currency_code=row.get("currency"),
                probability=int(str(row["probability"])),
                expected_close_date=(
                    (datetime.now(UTC) + timedelta(days=float(str(row["close_days"])))).date()
                ),
                owner_id=owner_id,
                won_at=won_at,
                lost_at=lost_at,
                lost_reason=row.get("lost_reason"),
                created_at=_ago(stage_changed_days),
            )
            session.add(opportunity)
            await session.flush()
            opportunity_ids.append(opportunity.id)
            opportunity_by_name[str(row["name"])] = opportunity.id

        # --- Customers -----------------------------------------------------
        customer_ids: list[uuid.UUID] = []
        for row in _CUSTOMER_ROWS:
            source_name = row.get("source_opportunity")
            source_id = (
                opportunity_by_name.get(str(source_name)) if source_name is not None else None
            )
            credit = row.get("credit_limit")
            customer = ErpCrmCustomerModel(
                tenant_id=tenant_id,
                customer_code=row["code"],
                name=row["name"],
                source_opportunity_id=source_id,
                email=row["email"],
                phone=row["phone"],
                credit_limit=Decimal(str(credit)) if credit is not None else None,
                currency_code=row.get("currency"),
                created_at=_ago(float(str(row["days_ago"]))),
            )
            session.add(customer)
            await session.flush()
            customer_ids.append(customer.id)

        # --- Contacts ------------------------------------------------------
        contact_ids: list[uuid.UUID] = []
        for row in _CONTACT_ROWS:
            contact = ErpCrmContactModel(
                tenant_id=tenant_id,
                customer_id=customer_ids[int(str(row["customer"]))],
                first_name=row["first"],
                last_name=row["last"],
                email=row["email"],
                phone=row["phone"],
                job_title=row["title"],
                is_primary=bool(row["primary"]),
                created_at=_ago(float(str(row["customer"])) * 2 + 2),
            )
            session.add(contact)
            await session.flush()
            contact_ids.append(contact.id)

        anchor_index: dict[tuple[str, int], uuid.UUID] = {}
        for i, lead_id in enumerate(lead_ids):
            anchor_index[("lead", i)] = lead_id
        for i, opportunity_id in enumerate(opportunity_ids):
            anchor_index[("opportunity", i)] = opportunity_id
        for i, customer_id in enumerate(customer_ids):
            anchor_index[("customer", i)] = customer_id
        for i, contact_id in enumerate(contact_ids):
            anchor_index[("contact", i)] = contact_id

        # --- Activities ----------------------------------------------------
        completed_count = 0
        for index, row in enumerate(_ACTIVITY_ROWS):
            anchor_type: str
            anchor_index_value: str
            anchor_type, anchor_index_value = row["anchor"]  # type: ignore[misc]
            completed = bool(row["completed"])
            due = _ago(float(str(row["due_days"])), hours=index % 4)
            activity = ErpCrmActivityModel(
                tenant_id=tenant_id,
                kind=row["kind"],
                entity_type=CrmEntityType(anchor_type),
                entity_id=anchor_index[(anchor_type, int(anchor_index_value))],
                subject=row["subject"],
                description=row.get("description"),
                due_at=due if row["kind"] in (ActivityKind.TASK, ActivityKind.FOLLOW_UP) else None,
                completed_at=_ago(2, hours=1) if completed else None,
                completed_by=owner_id if completed else None,
                owner_id=owner_id,
                created_at=_ago(max(2, float(str(row["due_days"])) + 1)),
            )
            session.add(activity)
            completed_count += 1 if completed else 0

        # --- Notes ---------------------------------------------------------
        for row in _NOTE_ROWS:
            n_anchor_type: str
            n_anchor_index_value: str
            n_anchor_type, n_anchor_index_value = row["anchor"]  # type: ignore[misc]
            note = ErpCrmNoteModel(
                tenant_id=tenant_id,
                entity_type=CrmEntityType(n_anchor_type),
                entity_id=anchor_index[(n_anchor_type, int(n_anchor_index_value))],
                body=row["body"],
                author_id=owner_id,
                created_at=_ago(max(1, 6 - int(n_anchor_index_value) % 5)),
            )
            session.add(note)

        # --- Timeline events ----------------------------------------------
        for i, lead_id in enumerate(lead_ids):
            days = float(str(LEAD_ROWS[i]["days_ago"]))
            session.add(
                ErpCrmTimelineEventModel(
                    tenant_id=tenant_id,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=lead_id,
                    event_type=CrmTimelineEventType.LEAD_CREATED,
                    title="Lead created",
                    actor_id=owner_id,
                    payload={"source": LEAD_ROWS[i]["source"], "email": LEAD_ROWS[i]["email"]},
                    created_at=_ago(days),
                )
            )
        for _, lead_id in qualified_by_company.items():
            session.add(
                ErpCrmTimelineEventModel(
                    tenant_id=tenant_id,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=lead_id,
                    event_type=CrmTimelineEventType.LEAD_QUALIFIED,
                    title="Lead qualified",
                    actor_id=owner_id,
                    created_at=_ago(10),
                )
            )
        for index, row in enumerate(_OPPORTUNITY_ROWS):
            if row["stage"] not in (OpportunityStage.WON, OpportunityStage.LOST):
                session.add(
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=opportunity_ids[index],
                        event_type=CrmTimelineEventType.OPPORTUNITY_STAGE_CHANGED,
                        title=f"Stage changed to {OpportunityStage(str(row['stage'])).value.replace('_', ' ')}",
                        actor_id=owner_id,
                        created_at=_ago(float(str(row["days_ago"]))),
                    )
                )
            if row["stage"] == OpportunityStage.WON:
                session.add(
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=opportunity_ids[index],
                        event_type=CrmTimelineEventType.OPPORTUNITY_WON,
                        title="Opportunity won",
                        actor_id=owner_id,
                        created_at=_ago(float(str(row["close_days"]))),
                    )
                )
            if row["stage"] == OpportunityStage.LOST:
                session.add(
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=opportunity_ids[index],
                        event_type=CrmTimelineEventType.OPPORTUNITY_LOST,
                        title="Opportunity lost",
                        actor_id=owner_id,
                        payload={"reason": row.get("lost_reason")},
                        created_at=_ago(float(str(row["close_days"]))),
                    )
                )
        for i, customer_id in enumerate(customer_ids):
            session.add(
                ErpCrmTimelineEventModel(
                    tenant_id=tenant_id,
                    entity_type=CrmEntityType.CUSTOMER,
                    entity_id=customer_id,
                    event_type=CrmTimelineEventType.CUSTOMER_CREATED,
                    title="Customer created",
                    actor_id=owner_id,
                    created_at=_ago(float(str(_CUSTOMER_ROWS[i]["days_ago"]))),
                )
            )
        for row in _ORDER_EVENTS:
            customer_index = int(str(row["customer"]))
            session.add(
                ErpCrmTimelineEventModel(
                    tenant_id=tenant_id,
                    entity_type=CrmEntityType.CUSTOMER,
                    entity_id=customer_ids[customer_index],
                    event_type=CrmTimelineEventType.ORDER_CREATED,
                    title="Order placed",
                    actor_id=owner_id,
                    payload={"order_number": row["order"], "total": row["total"]},
                    created_at=_ago(float(str(row["days_ago"]))),
                )
            )
        for index in (0, 2, 4):
            session.add(
                ErpCrmTimelineEventModel(
                    tenant_id=tenant_id,
                    entity_type=CrmEntityType.CUSTOMER,
                    entity_id=customer_ids[index],
                    event_type=CrmTimelineEventType.CONTACT_CREATED,
                    title="Contact added",
                    actor_id=owner_id,
                    created_at=_ago(float(str(_CUSTOMER_ROWS[index]["days_ago"])) - 2),
                )
            )

        await session.commit()

        counts = {
            "leads": len(lead_ids),
            "opportunities": len(opportunity_ids),
            "customers": len(customer_ids),
            "contacts": len(contact_ids),
            "activities": len(_ACTIVITY_ROWS),
            "notes": len(_NOTE_ROWS),
            "timeline_events": len(lead_ids)
            + len(qualified_by_company)
            + len(opportunity_ids)
            + len(customer_ids)
            + len(_ORDER_EVENTS)
            + 3,
            "completed_activities": completed_count,
        }
        logger.info("seed.crm.complete", tenant_id=str(tenant_id), **counts)
        return counts
