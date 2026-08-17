/**
 * HR API client (departments, employees, leave).
 *
 * Mirrors identity-api.ts: calls go through the same-origin /api/v1/* BFF
 * proxy, payloads are mapped from snake_case over the wire to camelCase here,
 * and every failure surfaces an `ApiError` the UI can render inline.
 */

import {
  apiFetch,
  apiList,
  apiPost,
  buildQueryString,
  type Paginated,
} from "@/lib/api/http";

export type EmployeeStatus = "active" | "on_leave" | "terminated";

export type LeaveRequestStatus = "pending" | "approved" | "rejected" | "cancelled";

export interface Money {
  amount: string;
  currency: string;
}

export interface Employee {
  id: string;
  employeeNumber: string;
  firstName: string;
  lastName: string;
  jobTitle: string;
  hireDate: string;
  employmentStatus: EmployeeStatus;
  email: string | null;
  phone: string | null;
  userId: string | null;
  departmentId: string | null;
  terminationDate: string | null;
  activeCompensation: Money | null;
  createdAt: string;
}

export interface Department {
  id: string;
  name: string;
  managerEmployeeId: string | null;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface LeaveRequest {
  id: string;
  employeeId: string;
  leaveType: string;
  startDate: string;
  endDate: string;
  days: number;
  status: LeaveRequestStatus;
  reason: string | null;
  approvedBy: string | null;
  approvedAt: string | null;
  createdAt: string;
}

export interface LeaveBalance {
  employeeId: string;
  leaveType: string;
  balance: number;
}

export interface LeaveMovement {
  id: string;
  employeeId: string;
  leaveType: string;
  qty: number;
  refType: string;
  refId: string | null;
  reason: string | null;
  occurredAt: string | null;
}

interface MoneyPayload {
  amount?: unknown;
  currency?: unknown;
}

interface EmployeePayload {
  id?: unknown;
  employee_number?: unknown;
  first_name?: unknown;
  last_name?: unknown;
  job_title?: unknown;
  hire_date?: unknown;
  employment_status?: unknown;
  email?: unknown;
  phone?: unknown;
  user_id?: unknown;
  department_id?: unknown;
  termination_date?: unknown;
  active_compensation?: MoneyPayload | null;
  created_at?: unknown;
}

interface DepartmentPayload {
  id?: unknown;
  name?: unknown;
  manager_employee_id?: unknown;
  is_active?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
}

interface LeaveRequestPayload {
  id?: unknown;
  employee_id?: unknown;
  leave_type?: unknown;
  start_date?: unknown;
  end_date?: unknown;
  days?: unknown;
  status?: unknown;
  reason?: unknown;
  approved_by?: unknown;
  approved_at?: unknown;
  created_at?: unknown;
}

interface LeaveBalancePayload {
  employee_id?: unknown;
  leave_type?: unknown;
  balance?: unknown;
}

interface LeaveMovementPayload {
  id?: unknown;
  employee_id?: unknown;
  leave_type?: unknown;
  qty?: unknown;
  ref_type?: unknown;
  ref_id?: unknown;
  reason?: unknown;
  occurred_at?: unknown;
}

function mapMoney(payload: MoneyPayload | null | undefined): Money | null {
  if (!payload) return null;
  return {
    amount: String(payload.amount ?? ""),
    currency: String(payload.currency ?? "USD"),
  };
}

function mapEmployee(payload: EmployeePayload): Employee {
  return {
    id: String(payload.id ?? ""),
    employeeNumber: String(payload.employee_number ?? ""),
    firstName: String(payload.first_name ?? ""),
    lastName: String(payload.last_name ?? ""),
    jobTitle: String(payload.job_title ?? ""),
    hireDate: String(payload.hire_date ?? ""),
    employmentStatus: String(payload.employment_status ?? "active") as EmployeeStatus,
    email: typeof payload.email === "string" ? payload.email : null,
    phone: typeof payload.phone === "string" ? payload.phone : null,
    userId: typeof payload.user_id === "string" ? payload.user_id : null,
    departmentId:
      typeof payload.department_id === "string" ? payload.department_id : null,
    terminationDate:
      typeof payload.termination_date === "string" ? payload.termination_date : null,
    activeCompensation: mapMoney(payload.active_compensation),
    createdAt: String(payload.created_at ?? ""),
  };
}

function mapDepartment(payload: DepartmentPayload): Department {
  return {
    id: String(payload.id ?? ""),
    name: String(payload.name ?? ""),
    managerEmployeeId:
      typeof payload.manager_employee_id === "string"
        ? payload.manager_employee_id
        : null,
    isActive: payload.is_active !== false,
    createdAt: String(payload.created_at ?? ""),
    updatedAt: String(payload.updated_at ?? ""),
  };
}

function mapLeaveRequest(payload: LeaveRequestPayload): LeaveRequest {
  return {
    id: String(payload.id ?? ""),
    employeeId: String(payload.employee_id ?? ""),
    leaveType: String(payload.leave_type ?? ""),
    startDate: String(payload.start_date ?? ""),
    endDate: String(payload.end_date ?? ""),
    days: typeof payload.days === "number" ? payload.days : 0,
    status: String(payload.status ?? "pending") as LeaveRequestStatus,
    reason: typeof payload.reason === "string" ? payload.reason : null,
    approvedBy: typeof payload.approved_by === "string" ? payload.approved_by : null,
    approvedAt: typeof payload.approved_at === "string" ? payload.approved_at : null,
    createdAt: String(payload.created_at ?? ""),
  };
}

function mapLeaveBalance(payload: LeaveBalancePayload): LeaveBalance {
  return {
    employeeId: String(payload.employee_id ?? ""),
    leaveType: String(payload.leave_type ?? ""),
    balance: typeof payload.balance === "number" ? payload.balance : 0,
  };
}

function mapLeaveMovement(payload: LeaveMovementPayload): LeaveMovement {
  return {
    id: String(payload.id ?? ""),
    employeeId: String(payload.employee_id ?? ""),
    leaveType: String(payload.leave_type ?? ""),
    qty: typeof payload.qty === "number" ? payload.qty : 0,
    refType: String(payload.ref_type ?? ""),
    refId: typeof payload.ref_id === "string" ? payload.ref_id : null,
    reason: typeof payload.reason === "string" ? payload.reason : null,
    occurredAt:
      typeof payload.occurred_at === "string" ? payload.occurred_at : null,
  };
}

export interface EmployeeListFilters {
  q?: string;
  status?: EmployeeStatus;
  departmentId?: string;
}

export async function listEmployees(input: {
  page?: number;
  pageSize?: number;
  filters?: EmployeeListFilters;
} = {}): Promise<Paginated<Employee>> {
  const result = await apiList<EmployeePayload>("/api/v1/hr/employees", {
    page: input.page,
    pageSize: input.pageSize,
    query: {
      q: input.filters?.q,
      status: input.filters?.status,
      department_id: input.filters?.departmentId,
    },
  });
  return { items: result.items.map(mapEmployee), meta: result.meta };
}

export async function getEmployee(employeeId: string): Promise<Employee> {
  const raw = await apiFetch<EmployeePayload>(`/api/v1/hr/employees/${employeeId}`);
  return mapEmployee(raw ?? {});
}

export async function createEmployee(input: {
  firstName: string;
  lastName: string;
  jobTitle: string;
  hireDate: string;
  email?: string;
  phone?: string;
  departmentId?: string;
  monthlySalary?: string;
  currency?: string;
}): Promise<Employee> {
  const raw = await apiPost<EmployeePayload>("/api/v1/hr/employees", {
    first_name: input.firstName,
    last_name: input.lastName,
    job_title: input.jobTitle,
    hire_date: input.hireDate,
    email: input.email,
    phone: input.phone,
    department_id: input.departmentId,
    monthly_salary: input.monthlySalary,
    currency: input.currency,
  });
  return mapEmployee(raw ?? {});
}

export async function updateEmployee(
  employeeId: string,
  input: Partial<{
    firstName: string;
    lastName: string;
    jobTitle: string;
    hireDate: string;
    email: string;
    phone: string;
    departmentId: string;
  }>,
): Promise<Employee> {
  const raw = await apiFetch<EmployeePayload>(`/api/v1/hr/employees/${employeeId}`, {
    method: "PATCH",
    body: JSON.stringify({
      first_name: input.firstName,
      last_name: input.lastName,
      job_title: input.jobTitle,
      hire_date: input.hireDate,
      email: input.email,
      phone: input.phone,
      department_id: input.departmentId,
    }),
  });
  return mapEmployee(raw ?? {});
}

export async function changeEmployeeStatus(
  employeeId: string,
  status: "active" | "on_leave",
): Promise<Employee> {
  const raw = await apiPost<EmployeePayload>(`/api/v1/hr/employees/${employeeId}/status`, {
    employment_status: status,
  });
  return mapEmployee(raw ?? {});
}

export async function terminateEmployee(
  employeeId: string,
  input: { terminationDate?: string; reason?: string },
): Promise<Employee> {
  const raw = await apiPost<EmployeePayload>(`/api/v1/hr/employees/${employeeId}/terminate`, {
    termination_date: input.terminationDate,
    reason: input.reason,
  });
  return mapEmployee(raw ?? {});
}

export async function listDepartments(): Promise<Department[]> {
  const items = await apiFetch<DepartmentPayload[]>("/api/v1/hr/departments");
  return (items ?? []).map(mapDepartment);
}

export async function createDepartment(input: {
  name: string;
  managerEmployeeId?: string;
}): Promise<Department> {
  const raw = await apiPost<DepartmentPayload>("/api/v1/hr/departments", {
    name: input.name,
    manager_employee_id: input.managerEmployeeId,
  });
  return mapDepartment(raw ?? {});
}

export async function updateDepartment(
  departmentId: string,
  input: { name?: string; managerEmployeeId?: string; isActive?: boolean },
): Promise<Department> {
  const raw = await apiFetch<DepartmentPayload>(`/api/v1/hr/departments/${departmentId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: input.name,
      manager_employee_id: input.managerEmployeeId,
      is_active: input.isActive,
    }),
  });
  return mapDepartment(raw ?? {});
}

export interface LeaveRequestListFilters {
  status?: LeaveRequestStatus;
  employeeId?: string;
  fromDate?: string;
  toDate?: string;
}

export async function listLeaveRequests(input: {
  page?: number;
  pageSize?: number;
  filters?: LeaveRequestListFilters;
} = {}): Promise<Paginated<LeaveRequest>> {
  const result = await apiList<LeaveRequestPayload>("/api/v1/hr/leave/requests", {
    page: input.page,
    pageSize: input.pageSize,
    query: {
      status: input.filters?.status,
      employee_id: input.filters?.employeeId,
      from_date: input.filters?.fromDate,
      to_date: input.filters?.toDate,
    },
  });
  return { items: result.items.map(mapLeaveRequest), meta: result.meta };
}

export async function createLeaveRequest(input: {
  employeeId: string;
  leaveType: string;
  startDate: string;
  endDate: string;
  reason?: string;
}): Promise<LeaveRequest> {
  const raw = await apiPost<LeaveRequestPayload>("/api/v1/hr/leave/requests", {
    employee_id: input.employeeId,
    leave_type: input.leaveType,
    start_date: input.startDate,
    end_date: input.endDate,
    reason: input.reason,
  });
  return mapLeaveRequest(raw ?? {});
}

export async function approveLeaveRequest(requestId: string): Promise<LeaveRequest> {
  const raw = await apiPost<LeaveRequestPayload>(
    `/api/v1/hr/leave/requests/${requestId}/approve`,
    {},
  );
  return mapLeaveRequest(raw ?? {});
}

export async function rejectLeaveRequest(
  requestId: string,
  reason?: string,
): Promise<LeaveRequest> {
  const raw = await apiPost<LeaveRequestPayload>(
    `/api/v1/hr/leave/requests/${requestId}/reject`,
    { reason },
  );
  return mapLeaveRequest(raw ?? {});
}

export async function cancelLeaveRequest(requestId: string): Promise<LeaveRequest> {
  const raw = await apiPost<LeaveRequestPayload>(
    `/api/v1/hr/leave/requests/${requestId}/cancel`,
    {},
  );
  return mapLeaveRequest(raw ?? {});
}

export async function getLeaveBalances(employeeId: string): Promise<LeaveBalance[]> {
  const items = await apiFetch<LeaveBalancePayload[]>(
    `/api/v1/hr/leave/balances?employee_id=${encodeURIComponent(employeeId)}`,
  );
  return (items ?? []).map(mapLeaveBalance);
}

export async function adjustLeaveBalance(input: {
  employeeId: string;
  leaveType: string;
  qty: number;
  reason: string;
}): Promise<LeaveBalance> {
  const raw = await apiPost<LeaveBalancePayload>("/api/v1/hr/leave/balances/adjust", {
    employee_id: input.employeeId,
    leave_type: input.leaveType,
    qty: input.qty,
    reason: input.reason,
  });
  return mapLeaveBalance(raw ?? {});
}

export async function accrueLeave(input: {
  employeeId: string;
  leaveType?: string;
  leaveYear?: number;
}): Promise<LeaveMovement | null> {
  const raw = await apiPost<LeaveMovementPayload | null>("/api/v1/hr/leave/accrue", {
    employee_id: input.employeeId,
    leave_type: input.leaveType,
    leave_year: input.leaveYear,
  });
  return raw ? mapLeaveMovement(raw) : null;
}

export async function listLeaveMovements(
  employeeId: string,
  leaveType?: string,
): Promise<LeaveMovement[]> {
  const items = await apiFetch<LeaveMovementPayload[]>(
    `/api/v1/hr/leave/movements${buildQueryString({
      employee_id: employeeId,
      leave_type: leaveType,
    })}`,
  );
  return (items ?? []).map(mapLeaveMovement);
}
