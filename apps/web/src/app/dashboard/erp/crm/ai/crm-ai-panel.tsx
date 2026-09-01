"use client";

import { FollowUpsFeed } from "@/components/dashboard/erp/crm/follow-ups-feed";

/**
 * CRM AI Insights panel — rendered inside the /dashboard/erp/crm/ai page.
 * Shows follow-up suggestions from the deterministic scan. Lead scores and
 * deal health badges are integrated directly into the leads/opportunities
 * tables via the AiScore and DealHealthBadge components.
 */
export function CrmAiPanel() {
  return (
    <div className="space-y-8">
      <FollowUpsFeed />
    </div>
  );
}
