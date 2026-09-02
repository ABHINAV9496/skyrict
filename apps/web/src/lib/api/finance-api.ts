import {
  apiFetch,
  apiFetchWithMeta,
  apiPost,
  type PaginationMeta,
} from "@/lib/api/http";

const FINANCE = "/api/v1/finance";

function queryString(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export type AccountType = "asset" | "liability" | "equity" | "revenue" | "expense";

export interface Account {
  id: string;
  tenant_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AccountCreateInput {
  code: string;
  name: string;
  account_type: AccountType;
}

export type EntryStatus = "draft" | "posted" | "voided";

export interface JournalLine {
  id: string;
  account_id: string;
  debit: number | null;
  credit: number | null;
  currency: string;
}

export interface JournalLineInput {
  account_code: string;
  debit?: number | null;
  credit?: number | null;
}

export interface JournalEntry {
  id: string;
  tenant_id: string;
  entry_date: string;
  memo: string | null;
  status: EntryStatus;
  source: string;
  source_ref: string | null;
  lines: JournalLine[];
  posted_at: string | null;
  posted_by_user_id: string | null;
  voided_at: string | null;
  reversal_entry_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface JournalEntryCreateInput {
  entry_date: string;
  memo?: string | null;
  lines: JournalLineInput[];
}

export type JournalEntryListParams = {
  status?: EntryStatus;
  from_date?: string;
  to_date?: string;
  offset?: number;
  limit?: number;
}

export interface FiscalPeriod {
  id: string;
  tenant_id: string;
  name: string;
  start_date: string;
  end_date: string;
  is_closed: boolean;
  created_at: string;
  updated_at: string;
}

export interface FiscalPeriodCreateInput {
  name: string;
  start_date: string;
  end_date: string;
}

export type InvoiceStatus = "draft" | "issued" | "approved" | "paid" | "voided";

export interface InvoiceLine {
  id: string;
  line_no: number;
  description: string;
  account_id: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface InvoiceLineInput {
  description: string;
  account_code: string;
  quantity: number;
  unit_price: number;
}

export interface Invoice {
  id: string;
  tenant_id: string;
  invoice_number: string;
  customer_id: string;
  customer_name?: string | null;
  invoice_date: string;
  due_date: string;
  status: InvoiceStatus;
  total: number;
  source: string;
  source_ref: string | null;
  source_order_number?: string | null;
  lines: InvoiceLine[];
  issued_at: string | null;
  approved_at: string | null;
  voided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvoiceCreateInput {
  customer_id: string;
  invoice_date: string;
  due_date: string;
  lines: InvoiceLineInput[];
}

export type InvoiceListParams = {
  status?: InvoiceStatus;
  offset?: number;
  limit?: number;
}

export interface Payment {
  id: string;
  tenant_id: string;
  payment_number: string;
  invoice_id: string;
  amount: number;
  method: string;
  paid_at: string;
  status: string;
  source: string;
  source_ref: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaymentApplyInput {
  amount: number;
  method: string;
  paid_at: string;
}

export interface TrialBalanceRow {
  account_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  debit: number;
  credit: number;
}

export interface TrialBalance {
  as_of: string;
  rows: TrialBalanceRow[];
  total_debit: number;
  total_credit: number;
}

export interface PnlLine {
  account_id: string;
  code: string;
  name: string;
  amount: number;
}

export interface ProfitAndLoss {
  from_date: string;
  to_date: string;
  revenue: PnlLine[];
  expenses: PnlLine[];
  total_revenue: number;
  total_expenses: number;
  net_income: number;
}

export interface BalanceSheetLine {
  account_id: string;
  code: string;
  name: string;
  balance: number;
}

export interface BalanceSheet {
  as_of: string;
  assets: BalanceSheetLine[];
  liabilities: BalanceSheetLine[];
  equity: BalanceSheetLine[];
  total_assets: number;
  total_liabilities: number;
  total_equity: number;
}

// --- Chart of accounts ---

export function listAccounts(activeOnly = true): Promise<Account[]> {
  const search = activeOnly ? "" : "?include_inactive=true";
  return apiFetch<Account[]>(`${FINANCE}/accounts${search}`);
}

export function createAccount(input: AccountCreateInput): Promise<Account> {
  return apiPost<Account>(`${FINANCE}/accounts`, input);
}

export function deactivateAccount(accountId: string): Promise<Account> {
  return apiFetch<Account>(`${FINANCE}/accounts/${accountId}`, { method: "DELETE" });
}

// --- Journal entries ---

export function listJournalEntries(
  params: JournalEntryListParams = {},
): Promise<{ data: JournalEntry[]; meta: PaginationMeta | null }> {
  return apiFetchWithMeta<JournalEntry[]>(`${FINANCE}/journal-entries${queryString(params)}`);
}

export function getJournalEntry(entryId: string): Promise<JournalEntry> {
  return apiFetch<JournalEntry>(`${FINANCE}/journal-entries/${entryId}`);
}

export function createJournalEntry(input: JournalEntryCreateInput): Promise<JournalEntry> {
  return apiPost<JournalEntry>(`${FINANCE}/journal-entries`, input);
}

export function postJournalEntry(entryId: string): Promise<JournalEntry> {
  return apiPost<JournalEntry>(`${FINANCE}/journal-entries/${entryId}/post`, {});
}

export function voidJournalEntry(entryId: string): Promise<JournalEntry> {
  return apiPost<JournalEntry>(`${FINANCE}/journal-entries/${entryId}/void`, {});
}

// --- Fiscal periods ---

export function listFiscalPeriods(): Promise<FiscalPeriod[]> {
  return apiFetch<FiscalPeriod[]>(`${FINANCE}/fiscal-periods`);
}

export function createFiscalPeriod(input: FiscalPeriodCreateInput): Promise<FiscalPeriod> {
  return apiPost<FiscalPeriod>(`${FINANCE}/fiscal-periods`, input);
}

export function closeFiscalPeriod(periodId: string): Promise<FiscalPeriod> {
  return apiPost<FiscalPeriod>(`${FINANCE}/fiscal-periods/${periodId}/close`, {});
}

// --- Invoices & payments ---

export function listInvoices(
  params: InvoiceListParams = {},
): Promise<{ data: Invoice[]; meta: PaginationMeta | null }> {
  return apiFetchWithMeta<Invoice[]>(`${FINANCE}/invoices${queryString(params)}`);
}

export function getInvoice(invoiceId: string): Promise<Invoice> {
  return apiFetch<Invoice>(`${FINANCE}/invoices/${invoiceId}`);
}

export function createInvoice(input: InvoiceCreateInput): Promise<Invoice> {
  return apiPost<Invoice>(`${FINANCE}/invoices`, input);
}

export function issueInvoice(invoiceId: string): Promise<Invoice> {
  return apiPost<Invoice>(`${FINANCE}/invoices/${invoiceId}/issue`, {});
}

export function approveInvoice(invoiceId: string): Promise<Invoice> {
  return apiPost<Invoice>(`${FINANCE}/invoices/${invoiceId}/approve`, {});
}

export function voidInvoice(invoiceId: string): Promise<Invoice> {
  return apiPost<Invoice>(`${FINANCE}/invoices/${invoiceId}/void`, {});
}

export function applyPayment(invoiceId: string, input: PaymentApplyInput): Promise<Payment> {
  return apiPost<Payment>(`${FINANCE}/invoices/${invoiceId}/payments`, input);
}

export function getPayment(paymentId: string): Promise<Payment> {
  return apiFetch<Payment>(`${FINANCE}/payments/${paymentId}`);
}

// --- Reports ---

export function getTrialBalance(asOf: string): Promise<TrialBalance> {
  return apiFetch<TrialBalance>(
    `${FINANCE}/reports/trial-balance${queryString({ as_of: asOf })}`,
  );
}

export function getProfitAndLoss(fromDate: string, toDate: string): Promise<ProfitAndLoss> {
  return apiFetch<ProfitAndLoss>(
    `${FINANCE}/reports/profit-and-loss${queryString({ from_date: fromDate, to_date: toDate })}`,
  );
}

export function getBalanceSheet(asOf: string): Promise<BalanceSheet> {
  return apiFetch<BalanceSheet>(
    `${FINANCE}/reports/balance-sheet${queryString({ as_of: asOf })}`,
  );
}

// --- Customers (CRM) ---

export interface Customer {
  id: string;
  tenant_id: string;
  customer_code: string;
  name: string;
  email: string | null;
  phone: string | null;
  credit_limit: number | null;
  currency: string | null;
  is_active: boolean;
}

export function listCustomers(): Promise<Customer[]> {
  return apiFetch<Customer[]>("/api/v1/crm/customers");
}

// --- Finance automation (SKY-56/SKY-64) ---

const AUTOMATION = "/api/v1/finance/automation";

export interface ArAgingBucket {
  bucket: string;
  count: number;
  amount: number;
  share: number;
}

export interface ArAging {
  as_of: string;
  total_ar: number;
  buckets: ArAgingBucket[];
}

export interface CloseChecklistItem {
  label: string;
  status: string;
  detail: string | null;
}

export interface CloseChecklist {
  period_id: string;
  period_name: string;
  items: CloseChecklistItem[];
  ready: boolean;
}

export interface DuplicateCandidate {
  entry_id: string;
  entry_date: string;
  memo: string | null;
  source_ref: string | null;
}

export interface DuplicateGroup {
  key: string;
  reason: string;
  entries: DuplicateCandidate[];
}

export interface AccountCodeSuggestion {
  description: string;
  suggested_code: string;
  suggested_name: string;
  confidence: number;
  reasoning: string;
  amount: number | null;
  side: "debit" | "credit";
  contra_code: string;
  contra_name: string;
}

export interface WorkingCapitalAlert {
  ratio: number;
  threshold: number;
  current_assets: number;
  current_liabilities: number;
  alert: boolean;
}

export interface HealthComponent {
  name: string;
  score: number;
  weight: number;
  detail: string | null;
}

export interface HealthScore {
  overall: number;
  components: HealthComponent[];
}

export interface CashflowPosition {
  month: string;
  opening: number;
  inflows: number;
  outflows: number;
  closing: number;
}

export interface CashflowProjection {
  positions: CashflowPosition[];
}

export interface ComparativePnlRow {
  account_code: string;
  account_name: string;
  current_amount: number;
  prior_amount: number;
  variance: number;
  variance_pct: number;
}

export interface ComparativePnl {
  current_from: string;
  current_to: string;
  prior_from: string;
  prior_to: string;
  rows: ComparativePnlRow[];
}

export interface FinanceAnomaly {
  id: string;
  entity_type: string;
  entity_id: string;
  anomaly_type: string;
  severity: string;
  description: string;
  status: string;
  detected_at: string;
}

export interface TenantSettings {
  working_capital_threshold: number;
}

export function getAging(asOf: string): Promise<ArAging> {
  return apiFetch<ArAging>(`${AUTOMATION}/aging${queryString({ as_of: asOf })}`);
}

export function getCloseChecklist(periodId: string): Promise<CloseChecklist> {
  return apiFetch<CloseChecklist>(
    `${AUTOMATION}/close-checklist${queryString({ period_id: periodId })}`,
  );
}

export function getDuplicates(): Promise<DuplicateGroup[]> {
  return apiFetch<DuplicateGroup[]>(`${AUTOMATION}/duplicates`);
}

export function suggestAccountCode(description: string): Promise<AccountCodeSuggestion> {
  return apiPost<AccountCodeSuggestion>(`${AUTOMATION}/suggest-account-code`, { description });
}

export function getWorkingCapitalAlert(asOf: string): Promise<WorkingCapitalAlert> {
  return apiFetch<WorkingCapitalAlert>(
    `${AUTOMATION}/working-capital-alert${queryString({ as_of: asOf })}`,
  );
}

export function getHealthScore(asOf: string): Promise<HealthScore> {
  return apiFetch<HealthScore>(`${AUTOMATION}/health-score${queryString({ as_of: asOf })}`);
}

export function getCashflowProjection(asOf: string): Promise<CashflowProjection> {
  return apiFetch<CashflowProjection>(
    `${AUTOMATION}/cashflow-projection${queryString({ as_of: asOf })}`,
  );
}

export function getAnomalies(): Promise<FinanceAnomaly[]> {
  return apiFetch<FinanceAnomaly[]>(`${AUTOMATION}/anomalies`);
}

export function scanAnomalies(): Promise<FinanceAnomaly[]> {
  return apiPost<FinanceAnomaly[]>(`${AUTOMATION}/anomalies/scan`, {});
}

export function getComparativePnl(
  currentFrom: string,
  currentTo: string,
  priorFrom: string,
  priorTo: string,
): Promise<ComparativePnl> {
  return apiFetch<ComparativePnl>(
    `${AUTOMATION}/reports/comparative-pnl${queryString({
      current_from: currentFrom,
      current_to: currentTo,
      prior_from: priorFrom,
      prior_to: priorTo,
    })}`,
  );
}

export function getAutomationSettings(): Promise<TenantSettings> {
  return apiFetch<TenantSettings>(`${AUTOMATION}/settings`);
}

export function updateAutomationSettings(threshold: number): Promise<TenantSettings> {
  return apiFetch<TenantSettings>(`${AUTOMATION}/settings`, {
    method: "PUT",
    body: JSON.stringify({ threshold }),
  });
}

export function reverseJournalEntry(entryId: string): Promise<JournalEntry> {
  return apiPost<JournalEntry>(`${AUTOMATION}/journal-entries/${entryId}/reverse`, {});
}
