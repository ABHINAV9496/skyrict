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
  invoice_date: string;
  due_date: string;
  status: InvoiceStatus;
  total: number;
  source: string;
  source_ref: string | null;
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

export function listAccounts(includeInactive = false): Promise<Account[]> {
  const search = includeInactive ? "?include_inactive=true" : "";
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
