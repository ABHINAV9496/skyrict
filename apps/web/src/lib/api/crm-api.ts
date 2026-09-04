/**
 * CRM & Sales API client (leads, opportunities, customers, orders, products).
 *
 * Modeled exactly on `identity-api.ts`: typed payload interfaces, `mapX`
 * mappers from the backend's snake_case wire format, and thin `apiFetch` /
 * `apiPost` calls through the same-origin /api/v1/* BFF proxy. The proxy
 * routes `crm`/`sales`/`inventory` to the core service and unwraps the
 * `skyrict_common` envelope; list endpoints are offset/limit paged.
 *
 * Nothing in the UI calls the backend directly - everything goes through the
 * BFF so the tenant slug stays server-derived and token refresh keeps working.
 */

import { apiFetch, apiFetchEnvelope, apiPatch, apiPost } from "@/lib/api/http";

// ---------------------------------------------------------------------------
// Domain enums (mirror `core.domain.value_objects`)
// ---------------------------------------------------------------------------

export type LeadStatus = "new" | "contacted" | "qualified" | "disqualified";
export type OpportunityStage =
  | "prospecting"
  | "qualified"
  | "proposal"
  | "negotiation"
  | "won"
  | "lost";
export type OrderStatus = "draft" | "confirmed" | "fulfilled" | "cancelled";
export type CreditCheckResult = "pending" | "passed" | "failed";

/** The unified activity catalog - follow-ups are `follow_up` rows, not a model. */
export type ActivityKind = "task" | "call" | "meeting" | "follow_up" | "email" | "note";

/** CRM anchor entity types for activities, notes, and the timeline. */
export type CrmEntityType = "lead" | "opportunity" | "customer" | "contact";

/**
 * Follow-up window labels the backend resolves to SQL on `due_at`/`completed_at`.
 * `open` is the catch-all "not completed"; `today`/`overdue`/`upcoming` narrow
 * it by due date; `completed` is everything with a completion timestamp.
 */
export type ActivityStatus = "open" | "overdue" | "today" | "upcoming" | "completed";

/** Merged timeline row provenance - the DB-layer UNION branch that emitted it. */
export type TimelineSource = "activity" | "note" | "event";

// ---------------------------------------------------------------------------
// Wire payloads (snake_case, defensive like identity-api.ts)
// ---------------------------------------------------------------------------

export interface ListResponse<T> {
  data: T[];
  meta: PaginationMeta;
}

export interface PaginationMeta {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface LeadPayload {
  id?: unknown;
  status?: unknown;
  source?: unknown;
  first_name?: unknown;
  last_name?: unknown;
  email?: unknown;
  phone?: unknown;
  company?: unknown;
  owner_id?: unknown;
  team_id?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface OpportunityPayload {
  id?: unknown;
  name?: unknown;
  lead_id?: unknown;
  stage?: unknown;
  amount?: unknown;
  currency?: unknown;
  probability?: unknown;
  expected_close_date?: unknown;
  owner_id?: unknown;
  team_id?: unknown;
  won_at?: unknown;
  lost_at?: unknown;
  lost_reason?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface CustomerPayload {
  id?: unknown;
  customer_code?: unknown;
  name?: unknown;
  source_opportunity_id?: unknown;
  email?: unknown;
  phone?: unknown;
  credit_limit?: unknown;
  currency?: unknown;
  is_active?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface OrderPayload {
  id?: unknown;
  order_number?: unknown;
  customer_id?: unknown;
  status?: unknown;
  credit_check?: unknown;
  subtotal?: unknown;
  discount?: unknown;
  tax?: unknown;
  total?: unknown;
  currency?: unknown;
  confirmed_at?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface OrderLinePayload {
  id?: unknown;
  order_id?: unknown;
  product_id?: unknown;
  product_name?: unknown;
  sku?: unknown;
  quantity?: unknown;
  unit_price?: unknown;
  discount?: unknown;
  tax?: unknown;
  line_total?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface ProductPayload {
  id?: unknown;
  sku?: unknown;
  name?: unknown;
  category?: unknown;
  unit?: unknown;
  sell_price?: unknown;
  reorder_point?: unknown;
  is_active?: unknown;
}

interface ContactPayload {
  id?: unknown;
  tenant_id?: unknown;
  customer_id?: unknown;
  first_name?: unknown;
  last_name?: unknown;
  email?: unknown;
  phone?: unknown;
  job_title?: unknown;
  is_primary?: unknown;
  is_active?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface ActivityPayload {
  id?: unknown;
  tenant_id?: unknown;
  kind?: unknown;
  entity_type?: unknown;
  entity_id?: unknown;
  subject?: unknown;
  description?: unknown;
  due_at?: unknown;
  completed_at?: unknown;
  completed_by?: unknown;
  notes?: unknown;
  owner_id?: unknown;
  team_id?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface NotePayload {
  id?: unknown;
  tenant_id?: unknown;
  entity_type?: unknown;
  entity_id?: unknown;
  body?: unknown;
  author_id?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface TimelineItemPayload {
  source?: unknown;
  id?: unknown;
  entity_type?: unknown;
  entity_id?: unknown;
  kind?: unknown;
  title?: unknown;
  body?: unknown;
  actor_id?: unknown;
  occurred_at?: unknown;
}

interface MoneyBucketPayload {
  currency?: unknown;
  amount?: unknown;
}

interface LeadStatusCountPayload {
  status?: unknown;
  count?: unknown;
}

interface LeadSourceCountPayload {
  source?: unknown;
  count?: unknown;
}

interface StageBucketPayload {
  stage?: unknown;
  count?: unknown;
  value?: unknown;
}

interface CrmOverviewPayload {
  leads?: unknown;
  opportunities?: unknown;
  customers?: unknown;
  activities?: unknown;
  recent_won?: unknown;
  top_opportunities?: unknown;
}

interface SearchHitPayload {
  entity_type?: unknown;
  entity_id?: unknown;
  title?: unknown;
  subtitle?: unknown;
}

// ---------------------------------------------------------------------------
// Domain models (what the UI consumes)
// ---------------------------------------------------------------------------

export interface Lead {
  id: string;
  status: LeadStatus;
  source: string | null;
  firstName: string | null;
  lastName: string | null;
  email: string | null;
  phone: string | null;
  company: string | null;
  ownerId: string | null;
  teamId: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface Opportunity {
  id: string;
  name: string;
  leadId: string | null;
  stage: OpportunityStage;
  amount: string | null;
  currency: string | null;
  probability: number;
  expectedCloseDate: string | null;
  ownerId: string | null;
  teamId: string | null;
  wonAt: string | null;
  lostAt: string | null;
  lostReason: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface Customer {
  id: string;
  customerCode: string;
  name: string;
  sourceOpportunityId: string | null;
  email: string | null;
  phone: string | null;
  creditLimit: string | null;
  currency: string | null;
  isActive: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface SalesOrder {
  id: string;
  orderNumber: string;
  customerId: string;
  status: OrderStatus;
  creditCheck: CreditCheckResult;
  subtotal: string;
  discount: string;
  tax: string;
  total: string;
  currency: string;
  confirmedAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface OrderLine {
  id: string;
  orderId: string;
  productId: string;
  productName: string;
  sku: string;
  quantity: string;
  unitPrice: string;
  discount: string;
  tax: string;
  lineTotal: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  category: string | null;
  unit: string | null;
  sellPrice: string | null;
  isActive: boolean;
}

export interface OpportunityStageChange {
  opportunity: Opportunity;
  customer: Customer | null;
}

export interface Contact {
  id: string;
  tenantId: string;
  customerId: string;
  firstName: string | null;
  lastName: string | null;
  email: string | null;
  phone: string | null;
  jobTitle: string | null;
  isPrimary: boolean;
  isActive: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface Activity {
  id: string;
  tenantId: string;
  kind: ActivityKind;
  entityType: CrmEntityType;
  entityId: string;
  subject: string;
  description: string | null;
  dueAt: string | null;
  completedAt: string | null;
  completedBy: string | null;
  notes: string | null;
  ownerId: string | null;
  teamId: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface CrmNote {
  id: string;
  tenantId: string;
  entityType: CrmEntityType;
  entityId: string;
  body: string;
  authorId: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface TimelineItem {
  source: TimelineSource;
  id: string;
  entityType: CrmEntityType;
  entityId: string;
  kind: string | null;
  title: string | null;
  body: string | null;
  actorId: string | null;
  occurredAt: string;
}

export interface MoneyBucket {
  currency: string;
  amount: string | null;
}

export interface StageBucket {
  stage: OpportunityStage;
  count: number;
  value: MoneyBucket[];
}

export interface CrmOverview {
  leads: {
    total: number;
    byStatus: { status: LeadStatus; count: number }[];
    bySource: { source: string | null; count: number }[];
  };
  opportunities: {
    openCount: number;
    openValue: MoneyBucket[];
    byStage: StageBucket[];
    wonCount: number;
    wonValue: MoneyBucket[];
    lostCount: number;
    winRate: number | null;
  };
  customers: { total: number; active: number };
  activities: { today: number; overdue: number; upcoming: number; completed30d: number };
  recentWon: Opportunity[];
  topOpportunities: Opportunity[];
}

export interface SearchHit {
  entityType: CrmEntityType;
  entityId: string;
  title: string;
  subtitle: string | null;
}

// ---------------------------------------------------------------------------
// Input shapes
// ---------------------------------------------------------------------------

export interface LeadCreateInput {
  source?: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
  company?: string;
  ownerId?: string;
  teamId?: string;
}

export interface LeadQualifyInput {
  amount?: string;
  currency?: string;
  probability?: number;
  expectedCloseDate?: string;
}

export interface CustomerInput {
  name: string;
  email?: string;
  phone?: string;
  creditLimit?: string;
  currency?: string;
}

export interface OrderLineInput {
  productId: string;
  quantity: string;
}

export interface ContactInput {
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
  jobTitle?: string;
  isPrimary?: boolean;
}

export interface ActivityInput {
  kind: ActivityKind;
  entityType: CrmEntityType;
  entityId: string;
  subject: string;
  description?: string;
  dueAt?: string;
  notes?: string;
  ownerId?: string;
  teamId?: string;
}

export interface ActivityUpdateInput {
  kind?: ActivityKind;
  subject?: string;
  description?: string;
  dueAt?: string;
  notes?: string;
  ownerId?: string;
  teamId?: string;
}

export interface NoteInput {
  entityType: CrmEntityType;
  entityId: string;
  body: string;
}

// ---------------------------------------------------------------------------
// Query builder
// ---------------------------------------------------------------------------

/** Build an offset/limit query string from a params object, skipping nullish values. */
export function listQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, typeof value === "boolean" ? String(value) : String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

// ---------------------------------------------------------------------------
// Mappers
// ---------------------------------------------------------------------------

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function amountString(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "string" ? Number(value) : Number(value);
  return Number.isFinite(parsed) ? String(parsed) : null;
}

function mapLead(raw: LeadPayload): Lead {
  return {
    id: String(raw.id ?? ""),
    status: (String(raw.status ?? "") as LeadStatus) || "new",
    source: optionalString(raw.source),
    firstName: optionalString(raw.first_name),
    lastName: optionalString(raw.last_name),
    email: optionalString(raw.email),
    phone: optionalString(raw.phone),
    company: optionalString(raw.company),
    ownerId: optionalString(raw.owner_id),
    teamId: optionalString(raw.team_id),
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapOpportunity(raw: OpportunityPayload): Opportunity {
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    leadId: optionalString(raw.lead_id),
    stage: (String(raw.stage ?? "prospecting") as OpportunityStage) || "prospecting",
    amount: amountString(raw.amount),
    currency: optionalString(raw.currency),
    probability:
      typeof raw.probability === "number" && Number.isFinite(raw.probability)
        ? raw.probability
        : Number(String(raw.probability ?? "0")) || 0,
    expectedCloseDate: optionalString(raw.expected_close_date),
    ownerId: optionalString(raw.owner_id),
    teamId: optionalString(raw.team_id),
    wonAt: optionalString(raw.won_at),
    lostAt: optionalString(raw.lost_at),
    lostReason: optionalString(raw.lost_reason),
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapCustomer(raw: CustomerPayload): Customer {
  return {
    id: String(raw.id ?? ""),
    customerCode: String(raw.customer_code ?? ""),
    name: String(raw.name ?? ""),
    sourceOpportunityId: optionalString(raw.source_opportunity_id),
    email: optionalString(raw.email),
    phone: optionalString(raw.phone),
    creditLimit: amountString(raw.credit_limit),
    currency: optionalString(raw.currency),
    isActive: raw.is_active !== false,
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapOrder(raw: OrderPayload): SalesOrder {
  return {
    id: String(raw.id ?? ""),
    orderNumber: String(raw.order_number ?? ""),
    customerId: String(raw.customer_id ?? ""),
    status: (String(raw.status ?? "draft") as OrderStatus) || "draft",
    creditCheck: (String(raw.credit_check ?? "pending") as CreditCheckResult) || "pending",
    subtotal: String(raw.subtotal ?? "0"),
    discount: String(raw.discount ?? "0"),
    tax: String(raw.tax ?? "0"),
    total: String(raw.total ?? "0"),
    currency: String(raw.currency ?? "USD"),
    confirmedAt: optionalString(raw.confirmed_at),
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapOrderLine(raw: OrderLinePayload): OrderLine {
  return {
    id: String(raw.id ?? ""),
    orderId: String(raw.order_id ?? ""),
    productId: String(raw.product_id ?? ""),
    productName: String(raw.product_name ?? ""),
    sku: String(raw.sku ?? ""),
    quantity: String(raw.quantity ?? "0"),
    unitPrice: String(raw.unit_price ?? "0"),
    discount: String(raw.discount ?? "0"),
    tax: String(raw.tax ?? "0"),
    lineTotal: String(raw.line_total ?? "0"),
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapProduct(raw: ProductPayload): Product {
  const sellPrice = Array.isArray(raw.sell_price) ? raw.sell_price[0] : null;
  return {
    id: String(raw.id ?? ""),
    sku: String(raw.sku ?? ""),
    name: String(raw.name ?? ""),
    category: optionalString(raw.category),
    unit: optionalString(raw.unit),
    sellPrice: amountString(sellPrice),
    isActive: raw.is_active !== false,
  };
}

function mapContact(raw: ContactPayload): Contact {
  return {
    id: String(raw.id ?? ""),
    tenantId: String(raw.tenant_id ?? ""),
    customerId: String(raw.customer_id ?? ""),
    firstName: optionalString(raw.first_name),
    lastName: optionalString(raw.last_name),
    email: optionalString(raw.email),
    phone: optionalString(raw.phone),
    jobTitle: optionalString(raw.job_title),
    isPrimary: raw.is_primary === true,
    isActive: raw.is_active !== false,
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapActivity(raw: ActivityPayload): Activity {
  return {
    id: String(raw.id ?? ""),
    tenantId: String(raw.tenant_id ?? ""),
    kind: (String(raw.kind ?? "task") as ActivityKind) || "task",
    entityType: (String(raw.entity_type ?? "customer") as CrmEntityType) || "customer",
    entityId: String(raw.entity_id ?? ""),
    subject: String(raw.subject ?? ""),
    description: optionalString(raw.description),
    dueAt: optionalString(raw.due_at),
    completedAt: optionalString(raw.completed_at),
    completedBy: optionalString(raw.completed_by),
    notes: optionalString(raw.notes),
    ownerId: optionalString(raw.owner_id),
    teamId: optionalString(raw.team_id),
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapNote(raw: NotePayload): CrmNote {
  return {
    id: String(raw.id ?? ""),
    tenantId: String(raw.tenant_id ?? ""),
    entityType: (String(raw.entity_type ?? "customer") as CrmEntityType) || "customer",
    entityId: String(raw.entity_id ?? ""),
    body: String(raw.body ?? ""),
    authorId: optionalString(raw.author_id),
    createdAt: optionalString(raw.created_at),
    updatedAt: optionalString(raw.updated_at),
  };
}

function mapTimelineItem(raw: TimelineItemPayload): TimelineItem {
  const source = (String(raw.source ?? "event") as TimelineSource) || "event";
  return {
    source,
    id: String(raw.id ?? ""),
    entityType: (String(raw.entity_type ?? "customer") as CrmEntityType) || "customer",
    entityId: String(raw.entity_id ?? ""),
    kind: optionalString(raw.kind),
    title: optionalString(raw.title),
    body: optionalString(raw.body),
    actorId: optionalString(raw.actor_id),
    occurredAt: String(raw.occurred_at ?? ""),
  };
}

function mapBucket(raw: MoneyBucketPayload): MoneyBucket {
  return {
    currency: String(raw.currency ?? "USD"),
    amount: amountString(raw.amount),
  };
}

function mapOverview(raw: CrmOverviewPayload): CrmOverview {
  const leads = (raw.leads ?? {}) as Record<string, unknown>;
  const opportunities = (raw.opportunities ?? {}) as Record<string, unknown>;
  const customers = (raw.customers ?? {}) as Record<string, unknown>;
  const activities = (raw.activities ?? {}) as Record<string, unknown>;

  const byStatus = (Array.isArray(leads.by_status) ? leads.by_status : []).map(
    (item) => item as LeadStatusCountPayload,
  );
  const bySource = (Array.isArray(leads.by_source) ? leads.by_source : []).map(
    (item) => item as LeadSourceCountPayload,
  );
  const byStage = (Array.isArray(opportunities.by_stage) ? opportunities.by_stage : []).map(
    (item) => item as StageBucketPayload,
  );
  const recentWon = (Array.isArray(raw.recent_won) ? raw.recent_won : []).map((item) =>
    mapOpportunity(item as OpportunityPayload),
  );
  const topOpportunities = (Array.isArray(raw.top_opportunities) ? raw.top_opportunities : [])
    .map((item) => mapOpportunity(item as OpportunityPayload));

  return {
    leads: {
      total: Number(leads.total ?? 0),
      byStatus: byStatus.map((item) => ({
        status: (String(item.status ?? "new") as LeadStatus) || "new",
        count: Number(item.count ?? 0),
      })),
      bySource: bySource.map((item) => ({
        source: optionalString(item.source),
        count: Number(item.count ?? 0),
      })),
    },
    opportunities: {
      openCount: Number(opportunities.open_count ?? 0),
      openValue: (Array.isArray(opportunities.open_value) ? opportunities.open_value : []).map(
        (item) => mapBucket(item as MoneyBucketPayload),
      ),
      byStage: byStage.map((item) => ({
        stage: (String(item.stage ?? "prospecting") as OpportunityStage) || "prospecting",
        count: Number(item.count ?? 0),
        value: (Array.isArray(item.value) ? item.value : []).map((bucket) =>
          mapBucket(bucket as MoneyBucketPayload),
        ),
      })),
      wonCount: Number(opportunities.won_count ?? 0),
      wonValue: (Array.isArray(opportunities.won_value) ? opportunities.won_value : []).map(
        (item) => mapBucket(item as MoneyBucketPayload),
      ),
      lostCount: Number(opportunities.lost_count ?? 0),
      winRate:
        typeof opportunities.win_rate === "number" && Number.isFinite(opportunities.win_rate)
          ? (opportunities.win_rate as number)
          : opportunities.win_rate === null || opportunities.win_rate === undefined
            ? null
            : Number(String(opportunities.win_rate)),
    },
    customers: { total: Number(customers.total ?? 0), active: Number(customers.active ?? 0) },
    activities: {
      today: Number(activities.today ?? 0),
      overdue: Number(activities.overdue ?? 0),
      upcoming: Number(activities.upcoming ?? 0),
      completed30d: Number(activities.completed_30d ?? 0),
    },
    recentWon,
    topOpportunities,
  };
}

function mapSearchHit(raw: SearchHitPayload): SearchHit {
  return {
    entityType: (String(raw.entity_type ?? "customer") as CrmEntityType) || "customer",
    entityId: String(raw.entity_id ?? ""),
    title: String(raw.title ?? ""),
    subtitle: optionalString(raw.subtitle),
  };
}

function mapList<T>(payload: { data?: unknown; meta?: unknown } | null, map: (raw: never) => T): ListResponse<T> {
  const data = Array.isArray(payload?.data) ? payload.data : [];
  const metaPayload = (payload?.meta ?? {}) as Record<string, unknown>;
  return {
    data: data.map((item) => map(item as never)),
    meta: {
      total: Number(metaPayload.total ?? 0),
      page: Number(metaPayload.page ?? 1),
      page_size: Number(metaPayload.page_size ?? 50),
      total_pages: Number(metaPayload.total_pages ?? 0),
    },
  };
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

export interface ListLeadsParams {
  status?: LeadStatus;
  source?: string;
  offset?: number;
  limit?: number;
}

export async function listLeads(params: ListLeadsParams = {}): Promise<ListResponse<Lead>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/leads${listQuery({ ...params })}`,
  );
  return mapList(raw, mapLead);
}

export async function createLead(input: LeadCreateInput): Promise<Lead> {
  const raw = await apiPost<LeadPayload>("/api/v1/crm/leads", {
    source: input.source || null,
    first_name: input.firstName || null,
    last_name: input.lastName || null,
    email: input.email || null,
    phone: input.phone || null,
    company: input.company || null,
    owner_id: input.ownerId || null,
    team_id: input.teamId || null,
  });
  return mapLead(raw ?? {});
}

export async function getLead(leadId: string): Promise<Lead> {
  const raw = await apiFetch<LeadPayload>(`/api/v1/crm/leads/${leadId}`);
  return mapLead(raw ?? {});
}

export async function qualifyLead(leadId: string, input: LeadQualifyInput = {}): Promise<Opportunity> {
  const raw = await apiPost<OpportunityPayload>(`/api/v1/crm/leads/${leadId}/qualify`, {
    amount: input.amount !== undefined ? input.amount : null,
    currency: input.currency ?? "USD",
    probability: input.probability ?? 0,
    expected_close_date: input.expectedCloseDate || null,
  });
  return mapOpportunity(raw ?? {});
}

export async function disqualifyLead(leadId: string): Promise<Lead> {
  const raw = await apiPost<LeadPayload>(`/api/v1/crm/leads/${leadId}/disqualify`, {});
  return mapLead(raw ?? {});
}

// ---------------------------------------------------------------------------
// Opportunities
// ---------------------------------------------------------------------------

export interface ListOpportunitiesParams {
  stage?: OpportunityStage;
  offset?: number;
  limit?: number;
}

export async function listOpportunities(
  params: ListOpportunitiesParams = {},
): Promise<ListResponse<Opportunity>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/opportunities${listQuery({ ...params })}`,
  );
  return mapList(raw, mapOpportunity);
}

export async function getOpportunity(opportunityId: string): Promise<Opportunity> {
  const raw = await apiFetch<OpportunityPayload>(`/api/v1/crm/opportunities/${opportunityId}`);
  return mapOpportunity(raw ?? {});
}

export async function changeOpportunityStage(
  opportunityId: string,
  stage: OpportunityStage,
  lostReason?: string,
): Promise<OpportunityStageChange> {
  const raw = await apiPost<{
    opportunity?: unknown;
    customer?: unknown;
  }>(`/api/v1/crm/opportunities/${opportunityId}/stage`, {
    stage,
    lost_reason: lostReason || null,
  });
  return {
    opportunity: mapOpportunity((raw?.opportunity ?? {}) as OpportunityPayload),
    customer:
      raw?.customer === null || raw?.customer === undefined
        ? null
        : mapCustomer(raw.customer as CustomerPayload),
  };
}

// ---------------------------------------------------------------------------
// Customers
// ---------------------------------------------------------------------------

export interface ListCustomersParams {
  includeInactive?: boolean;
  offset?: number;
  limit?: number;
}

export async function listCustomers(params: ListCustomersParams = {}): Promise<ListResponse<Customer>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/customers${listQuery({ ...params })}`,
  );
  return mapList(raw, mapCustomer);
}

export async function createCustomer(input: CustomerInput): Promise<Customer> {
  const raw = await apiPost<CustomerPayload>("/api/v1/crm/customers", {
    name: input.name,
    email: input.email || null,
    phone: input.phone || null,
    credit_limit: input.creditLimit !== undefined ? input.creditLimit : null,
    currency: input.currency ?? "USD",
  });
  return mapCustomer(raw ?? {});
}

export async function getCustomer(customerId: string): Promise<Customer> {
  const raw = await apiFetch<CustomerPayload>(`/api/v1/crm/customers/${customerId}`);
  return mapCustomer(raw ?? {});
}

export async function updateCustomer(customerId: string, changes: Partial<CustomerInput>): Promise<Customer> {
  const raw = await apiFetch<CustomerPayload>(`/api/v1/crm/customers/${customerId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: changes.name ?? null,
      email: changes.email ?? null,
      phone: changes.phone ?? null,
      credit_limit: changes.creditLimit !== undefined ? changes.creditLimit : null,
      currency: changes.currency ?? "USD",
    }),
  });
  return mapCustomer(raw ?? {});
}

export async function deactivateCustomer(customerId: string): Promise<Customer> {
  const raw = await apiFetch<CustomerPayload>(`/api/v1/crm/customers/${customerId}`, {
    method: "DELETE",
  });
  return mapCustomer(raw ?? {});
}

// ---------------------------------------------------------------------------
// Orders
// ---------------------------------------------------------------------------

export interface ListOrdersParams {
  status?: OrderStatus;
  customerId?: string;
  offset?: number;
  limit?: number;
}

export async function listOrders(params: ListOrdersParams = {}): Promise<ListResponse<SalesOrder>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/sales/orders${listQuery({
      status: params.status,
      customer_id: params.customerId,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
  return mapList(raw, mapOrder);
}

export async function getOrder(orderId: string): Promise<SalesOrder> {
  const raw = await apiFetch<OrderPayload>(`/api/v1/sales/orders/${orderId}`);
  return mapOrder(raw ?? {});
}

export async function listOrderLines(orderId: string): Promise<OrderLine[]> {
  const raw = await apiFetchEnvelope<{ data?: unknown }>(
    `/api/v1/sales/orders/${orderId}/lines`,
  );
  const data = Array.isArray(raw?.data) ? raw.data : [];
  return data.map((item) => mapOrderLine(item as OrderLinePayload));
}

export async function createOrder(input: {
  customerId: string;
  lines: OrderLineInput[];
}): Promise<SalesOrder> {
  const raw = await apiPost<OrderPayload>("/api/v1/sales/orders", {
    customer_id: input.customerId,
    lines: input.lines.map((line) => ({
      product_id: line.productId,
      quantity: line.quantity,
    })),
  });
  return mapOrder(raw ?? {});
}

export async function confirmOrder(orderId: string): Promise<SalesOrder> {
  const raw = await apiPost<OrderPayload>(`/api/v1/sales/orders/${orderId}/confirm`, {});
  return mapOrder(raw ?? {});
}

export async function fulfilOrder(orderId: string): Promise<SalesOrder> {
  const raw = await apiPost<OrderPayload>(`/api/v1/sales/orders/${orderId}/fulfil`, {});
  return mapOrder(raw ?? {});
}

export async function cancelOrder(orderId: string): Promise<SalesOrder> {
  const raw = await apiPost<OrderPayload>(`/api/v1/sales/orders/${orderId}/cancel`, {});
  return mapOrder(raw ?? {});
}

// ---------------------------------------------------------------------------
// Products (used by the order-creation picker)
// ---------------------------------------------------------------------------

export interface ListProductsParams {
  offset?: number;
  limit?: number;
}

export async function listProducts(params: ListProductsParams = {}): Promise<ListResponse<Product>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/inventory/products${listQuery({ ...params })}`,
  );
  return mapList(raw, mapProduct);
}

// ---------------------------------------------------------------------------
// Contacts
// ---------------------------------------------------------------------------

export interface ListContactsParams {
  customerId?: string;
  includeInactive?: boolean;
  offset?: number;
  limit?: number;
}

export async function listContacts(
  params: ListContactsParams = {},
): Promise<ListResponse<Contact>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/contacts${listQuery({
      customer_id: params.customerId,
      include_inactive: params.includeInactive,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
  return mapList(raw, mapContact);
}

export async function createContact(customerId: string, input: ContactInput): Promise<Contact> {
  const raw = await apiPost<ContactPayload>(`/api/v1/crm/customers/${customerId}/contacts`, {
    first_name: input.firstName || null,
    last_name: input.lastName || null,
    email: input.email || null,
    phone: input.phone || null,
    job_title: input.jobTitle || null,
    is_primary: input.isPrimary ?? false,
  });
  return mapContact(raw ?? {});
}

export async function getContact(contactId: string): Promise<Contact> {
  const raw = await apiFetch<ContactPayload>(`/api/v1/crm/contacts/${contactId}`);
  return mapContact(raw ?? {});
}

export async function updateContact(
  contactId: string,
  changes: Partial<ContactInput>,
): Promise<Contact> {
  const raw = await apiPatch<ContactPayload>(`/api/v1/crm/contacts/${contactId}`, {
    first_name: changes.firstName ?? null,
    last_name: changes.lastName ?? null,
    email: changes.email ?? null,
    phone: changes.phone ?? null,
    job_title: changes.jobTitle ?? null,
    is_primary: changes.isPrimary ?? null,
  });
  return mapContact(raw ?? {});
}

export async function deactivateContact(contactId: string): Promise<Contact> {
  const raw = await apiFetch<ContactPayload>(`/api/v1/crm/contacts/${contactId}`, {
    method: "DELETE",
  });
  return mapContact(raw ?? {});
}

// ---------------------------------------------------------------------------
// Activities (the unified follow-up catalog)
// ---------------------------------------------------------------------------

export interface ListActivitiesParams {
  entityType?: CrmEntityType;
  entityId?: string;
  kind?: ActivityKind;
  status?: ActivityStatus;
  assigneeId?: string;
  offset?: number;
  limit?: number;
}

export async function listActivities(
  params: ListActivitiesParams = {},
): Promise<ListResponse<Activity>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/activities${listQuery({
      entity_type: params.entityType,
      entity_id: params.entityId,
      kind: params.kind,
      status: params.status,
      assignee_id: params.assigneeId,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
  return mapList(raw, mapActivity);
}

export async function createActivity(input: ActivityInput): Promise<Activity> {
  const raw = await apiPost<ActivityPayload>("/api/v1/crm/activities", {
    kind: input.kind,
    entity_type: input.entityType,
    entity_id: input.entityId,
    subject: input.subject,
    description: input.description || null,
    due_at: input.dueAt || null,
    notes: input.notes || null,
    owner_id: input.ownerId || null,
    team_id: input.teamId || null,
  });
  return mapActivity(raw ?? {});
}

export async function updateActivity(
  activityId: string,
  changes: ActivityUpdateInput,
): Promise<Activity> {
  const raw = await apiPatch<ActivityPayload>(`/api/v1/crm/activities/${activityId}`, {
    kind: changes.kind ?? null,
    subject: changes.subject ?? null,
    description: changes.description ?? null,
    due_at: changes.dueAt ?? null,
    notes: changes.notes ?? null,
    owner_id: changes.ownerId ?? null,
    team_id: changes.teamId ?? null,
  });
  return mapActivity(raw ?? {});
}

export async function completeActivity(activityId: string): Promise<Activity> {
  const raw = await apiPost<ActivityPayload>(`/api/v1/crm/activities/${activityId}/complete`, {});
  return mapActivity(raw ?? {});
}

export async function deleteActivity(activityId: string): Promise<Activity> {
  const raw = await apiFetch<ActivityPayload>(`/api/v1/crm/activities/${activityId}`, {
    method: "DELETE",
  });
  return mapActivity(raw ?? {});
}

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

export interface ListNotesParams {
  entityType?: CrmEntityType;
  entityId?: string;
  offset?: number;
  limit?: number;
}

export async function listNotes(params: ListNotesParams = {}): Promise<ListResponse<CrmNote>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/notes${listQuery({
      entity_type: params.entityType,
      entity_id: params.entityId,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
  return mapList(raw, mapNote);
}

export async function createNote(input: NoteInput): Promise<CrmNote> {
  const raw = await apiPost<NotePayload>("/api/v1/crm/notes", {
    entity_type: input.entityType,
    entity_id: input.entityId,
    body: input.body,
  });
  return mapNote(raw ?? {});
}

export async function deleteNote(noteId: string): Promise<CrmNote> {
  const raw = await apiFetch<NotePayload>(`/api/v1/crm/notes/${noteId}`, { method: "DELETE" });
  return mapNote(raw ?? {});
}

// ---------------------------------------------------------------------------
// Timeline (merged activities + notes + business events)
// ---------------------------------------------------------------------------

export interface ListTimelineParams {
  offset?: number;
  limit?: number;
}

export async function listTimeline(
  entityType: CrmEntityType,
  entityId: string,
  params: ListTimelineParams = {},
): Promise<ListResponse<TimelineItem>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/timeline${listQuery({
      entity_type: entityType,
      entity_id: entityId,
      offset: params.offset,
      limit: params.limit,
    })}`,
  );
  return mapList(raw, mapTimelineItem);
}

export async function listRecentTimeline(
  params: ListTimelineParams = {},
): Promise<ListResponse<TimelineItem>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/timeline/recent${listQuery({
      offset: params.offset,
      limit: params.limit ?? 10,
    })}`,
  );
  return mapList(raw, mapTimelineItem);
}

// ---------------------------------------------------------------------------
// Overview + search
// ---------------------------------------------------------------------------

export async function getCrmOverview(): Promise<CrmOverview> {
  const raw = await apiFetch<CrmOverviewPayload>("/api/v1/crm/overview");
  return mapOverview(raw ?? {});
}

export interface SearchCrmParams {
  type?: CrmEntityType;
  offset?: number;
  limit?: number;
}

export async function searchCrm(
  q: string,
  params: SearchCrmParams = {},
): Promise<ListResponse<SearchHit>> {
  const raw = await apiFetchEnvelope<{ data?: unknown; meta?: unknown }>(
    `/api/v1/crm/search${listQuery({ q, type: params.type, offset: params.offset, limit: params.limit })}`,
  );
  return mapList(raw, mapSearchHit);
}
