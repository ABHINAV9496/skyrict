import { apiFetch, apiPost } from "@/lib/api/http";

const APPROVAL = "/api/v1/approval";

/** AI routing suggestion surfaced to a reviewer (advisory only). */
export interface ApprovalSuggestion {
    recommendation: string | null;
    confidence: string | null;
    reasoning: string | null;
    model_used: string | null;
    suggested_approver_id: string | null;
}

/** One pending inbox item: the instance context + the current step. */
export interface ApprovalInboxItem {
    instance_id: string;
    resource_type: string;
    resource_id: string;
    resource_label: string;
    status: string;
    submitted_by: string;
    submitted_at: string;
    current_step_index: number;
    step_key: string;
    step_status: string;
    sla_due_at: string | null;
    eligible_as: string;
    delegated_from: string | null;
    suggestion: ApprovalSuggestion | null;
}

/** One step of an instance, including its decision fields. */
export interface ApprovalStep {
    step_index: number;
    step_key: string;
    assignee_kind: string;
    assignee_value: string;
    status: string;
    decided_by: string | null;
    decided_at: string | null;
    sla_due_at: string | null;
    delegated_from: string | null;
}

/** One append-only audit transition (the instance's decision history). */
export interface ApprovalTransition {
    new_state: string;
    previous_state: string | null;
    actor_type: string;
    actor_id: string | null;
    reason: string | null;
    step_key: string | null;
    occurred_at: string | null;
}

/** Full instance detail: header, steps, transitions and the suggestion. */
export interface ApprovalInstance {
    instance_id: string;
    definition_id: string;
    definition_version: number;
    resource_type: string;
    resource_id: string;
    resource_label: string;
    status: string;
    current_step_index: number;
    submitted_by: string;
    submitted_at: string;
    completed_at: string | null;
    sla_due_at: string | null;
    suggestion: ApprovalSuggestion | null;
    steps: ApprovalStep[];
    transitions: ApprovalTransition[];
}

export type ApprovalDecision = "approve" | "reject" | "request_changes";

/** The outcome of a decision: the instance + the decided step. */
export interface ApprovalDecisionResult {
    instance_id: string;
    resource_type: string;
    resource_id: string;
    instance_status: string;
    step_key: string;
    step_status: string;
    instance_completed: boolean;
}

/** List the current user's pending approval inbox (limit clamped by backend). */
export function listApprovalInbox(limit = 100): Promise<ApprovalInboxItem[]> {
    return apiFetch<ApprovalInboxItem[]>(`${APPROVAL}/inbox?limit=${limit}`);
}

/** Full detail for one instance, including its audit transitions. */
export function getApprovalInstance(instanceId: string): Promise<ApprovalInstance> {
    return apiFetch<ApprovalInstance>(`${APPROVAL}/inbox/${instanceId}`);
}

/** Record a reviewer decision on the instance's current step. */
export function decideApproval(
    instanceId: string,
    decision: ApprovalDecision,
    reason?: string,
): Promise<ApprovalDecisionResult> {
    return apiPost<ApprovalDecisionResult>(`${APPROVAL}/inbox/${instanceId}/decide`, {
        decision,
        ...(reason !== undefined ? { reason } : {}),
    });
}