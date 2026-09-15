/**
 * Client for the HR-AI-004 L4 what-if planning API.
 *
 * All calls go through /api/v1/ai/hr/l4/* which the BFF proxies to the core
 * monolith's ai_hr router, which then relays scenario CRUD to the ai-agent
 * engine (JWT + tenant slug re-verified at both hops). Money arrives as
 * decimal *strings* everywhere - never coerce through Number() for display.
 */

import { apiFetch, apiPostBody, buildQueryString } from "@/lib/api/http";

const L4 = "/api/v1/ai/hr/l4";

export interface PayrollBaseEmployee {
    employee_id: string;
    employee_number: string;
    first_name: string;
    last_name: string;
    department_id: string | null;
    department_name: string | null;
    job_title: string;
    employment_status: string;
    hire_date: string;
    monthly_salary: string;
    currency: string;
    monthly_benefit_cost: string;
}

export interface PayrollBase {
    tenant_id: string;
    as_of: string;
    currency: string;
    headcount: number;
    monthly_salary_total: string;
    monthly_benefit_cost_total: string;
    employees: PayrollBaseEmployee[];
}

export interface ProjectionMonth {
    month: number;
    headcount: number;
    salary_cost: string;
    benefit_cost: string;
    total_cost: string;
}

export interface Projection {
    currency: string;
    horizon: number;
    months: ProjectionMonth[];
    salary_total: string;
    benefit_total: string;
    grand_total: string;
}

export interface ScenarioListItem {
    id: string;
    name: string;
    base_as_of: string;
    horizon: number;
    created_at: string;
}

export interface Scenario {
    id: string;
    name: string;
    description: string | null;
    base_as_of: string;
    horizon: number;
    currency: string;
    actions: Record<string, unknown>[];
    projection: Projection;
    created_by: string;
    created_at: string;
}

export interface ScenarioCompareItem {
    id: string;
    name: string;
    base_as_of: string;
    horizon: number;
    projection: Projection;
}

export interface SalaryMeritAction {
    type: "salary_merit";
    percent: string;
    effective_month: number;
}

export interface NewHireAction {
    type: "new_hire";
    effective_month: number;
    employee: {
        employee_number?: string;
        first_name: string;
        last_name: string;
        department_id?: string;
        department_name?: string;
        job_title: string;
        hire_date: string;
        monthly_salary: string;
        currency: string;
        monthly_benefit_cost: string;
    };
}

export interface ReductionAction {
    type: "reduction";
    employee_id: string;
    effective_month: number;
}

export interface BenefitChangeAction {
    type: "benefit_change";
    employee_id: string;
    monthly_benefit_cost: string;
    effective_month: number;
}

export type ScenarioAction =
    | SalaryMeritAction
    | NewHireAction
    | ReductionAction
    | BenefitChangeAction;

export interface ScenarioCreateInput {
    name: string;
    description?: string;
    base_as_of: string;
    horizon: number;
    actions: ScenarioAction[];
}

export async function getPayrollBase(asOf?: string): Promise<PayrollBase> {
    return apiFetch<PayrollBase>(
        `${L4}/payroll-base${buildQueryString({ as_of: asOf ?? "" })}`,
    );
}

export async function listScenarios(): Promise<ScenarioListItem[]> {
    return apiFetch<ScenarioListItem[]>(`${L4}/scenarios`);
}

export async function createScenario(
    input: ScenarioCreateInput,
): Promise<Scenario> {
    return apiPostBody<Scenario>(`${L4}/scenarios`, input);
}

export async function getScenario(id: string): Promise<Scenario> {
    return apiFetch<Scenario>(`${L4}/scenarios/${id}`);
}

export async function compareScenarios(
    ids: string[],
): Promise<ScenarioCompareItem[]> {
    const query = ids
        .map((id) => `ids=${encodeURIComponent(id)}`)
        .join("&");
    return apiFetch<ScenarioCompareItem[]>(
        query ? `${L4}/scenarios/compare?${query}` : `${L4}/scenarios/compare`,
    );
}