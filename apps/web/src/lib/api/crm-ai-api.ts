/**
 * CRM AI features API client (SKY-61, SKY-91).
 *
 * Lead scoring, deal health, follow-up suggestions, and the pipeline anomaly
 * inbox. All calls go through /api/v1/ai/crm/* which the BFF proxies to
 * core's AI router, which then forwards to the ai-agent microservice.
 */

import { apiFetchBody, apiPostBody } from "@/lib/api/http";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type HealthBand = "green" | "yellow" | "red";

export type FollowUpType = "email" | "call" | "meeting" | "task";

export interface LeadScore {
    lead_id: string;
    score: number;
    confidence: number;
    factors: string[];
    model_version: string;
    computed_at: string;
}

export interface DealHealth {
    opportunity_id: string;
    health: HealthBand;
    confidence: number;
    risk_factors: string[];
    recommended_actions: string[];
    engagement_velocity: number | null;
    days_in_stage: number | null;
    computed_at: string;
}

export interface DealHealthSweep {
    assessed: number;
    healthy: number;
    at_risk: number;
    critical: number;
}

export interface FollowUpItem {
    id: string;
    entity_type: string;
    entity_id: string;
    suggestion_type: FollowUpType;
    draft_content: string;
    reasoning: string;
    confidence: number;
    status: string;
    created_at: string;
    expires_at: string;
}

export type CrmAnomalySeverity = "critical" | "warning" | "info";

export type CrmAnomalyStatus = "open" | "resolved" | "dismissed";

export interface CrmAnomalyItem {
    id: string;
    opportunity_id: string;
    rule_id: string;
    severity: CrmAnomalySeverity;
    status: CrmAnomalyStatus;
    title: string;
    description: string;
    context: Record<string, unknown>;
    detected_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const CRM_AI = "/api/v1/ai/crm";

/**
 * Compute and persist a deterministic AI score for a lead.
 */
export async function scoreLead(leadId: string): Promise<LeadScore> {
    return apiPostBody<LeadScore>(`${CRM_AI}/leads/${leadId}/score`, {});
}

/**
 * Compute and persist a deterministic health assessment for an opportunity.
 */
export async function getDealHealth(
    opportunityId: string,
): Promise<DealHealth> {
    return apiFetchBody<DealHealth>(
        `${CRM_AI}/opportunities/${opportunityId}/health`,
    );
}

/**
 * Recheck + persist deal health for every open opportunity expected to close
 * within the next 12 months (manual twin of the scheduled nightly sweep).
 */
export async function sweepDealHealth(): Promise<DealHealthSweep> {
    return apiPostBody<DealHealthSweep>(`${CRM_AI}/opportunities/sweep`, {});
}

/**
 * List pending follow-up suggestions for the authenticated user.
 */
export async function listFollowUps(): Promise<FollowUpItem[]> {
    return apiFetchBody<FollowUpItem[]>(`${CRM_AI}/follow-ups`);
}

/**
 * Apply a follow-up suggestion (one-click send).
 * Requires an activity_id - the UUID of the CRM activity created in core.
 */
export async function applyFollowUp(
    followUpId: string,
    activityId: string,
): Promise<FollowUpItem> {
    return apiPostBody<FollowUpItem>(
        `${CRM_AI}/follow-ups/${followUpId}/apply`,
        {
            activity_id: activityId,
        },
    );
}

/**
 * Dismiss a pending follow-up suggestion.
 */
export async function dismissFollowUp(
    followUpId: string,
): Promise<FollowUpItem> {
    return apiPostBody<FollowUpItem>(
        `${CRM_AI}/follow-ups/${followUpId}/dismiss`,
        {},
    );
}

/**
 * List open CRM pipeline anomalies for the tenant (newest first).
 */
export async function listCrmAnomalies(): Promise<CrmAnomalyItem[]> {
    return apiFetchBody<CrmAnomalyItem[]>(`${CRM_AI}/anomalies`);
}

/**
 * Resolve an open CRM anomaly - the rep acted on the flagged deal.
 */
export async function resolveCrmAnomaly(
    anomalyId: string,
): Promise<CrmAnomalyItem> {
    return apiPostBody<CrmAnomalyItem>(
        `${CRM_AI}/anomalies/${anomalyId}/resolve`,
        {},
    );
}

/**
 * Dismiss an open CRM anomaly as a false positive.
 */
export async function dismissCrmAnomaly(
    anomalyId: string,
): Promise<CrmAnomalyItem> {
    return apiPostBody<CrmAnomalyItem>(
        `${CRM_AI}/anomalies/${anomalyId}/dismiss`,
        {},
    );
}
