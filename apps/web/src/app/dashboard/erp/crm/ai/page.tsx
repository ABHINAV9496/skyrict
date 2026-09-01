import { Sparkles } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CrmSectionTabs } from "@/components/dashboard/erp/crm/crm-section-tabs";
import { CrmAiPanel } from "./crm-ai-panel";

export default function CrmAiPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="AI Insights"
          description="Lead scores, deal health, and AI-generated follow-up suggestions."
          icon={Sparkles}
        />
        <CrmSectionTabs />
        <CrmAiPanel />
      </div>
    </RequirePermission>
  );
}
