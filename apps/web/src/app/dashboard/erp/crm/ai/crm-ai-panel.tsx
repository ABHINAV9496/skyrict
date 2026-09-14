"use client";

import { AnomaliesFeed } from "@/components/dashboard/erp/crm/anomalies-feed";
import { FollowUpsFeed } from "@/components/dashboard/erp/crm/follow-ups-feed";

/**
 * CRM AI Insights panel - rendered inside the /dashboard/erp/crm/ai page.
 * Shows the pipeline anomaly inbox from the hourly scan and follow-up
 * suggestions from the deterministic scan. Lead scores and deal health
 * badges are integrated directly into the leads/opportunities tables via
 * the AiScore and DealHealthBadge components.
 */
export function CrmAiPanel() {
    return (
        <div className="space-y-8">
            <AnomaliesFeed />
            <FollowUpsFeed />
        </div>
    );
}