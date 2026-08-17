import { LayoutDashboard } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CrmSectionTabs } from "@/components/dashboard/erp/crm/crm-section-tabs";
import { CrmOverview } from "@/components/dashboard/erp/crm/crm-overview";

export default function CrmOverviewPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="CRM overview"
          description="The pipeline, customer base, and follow-up load in your workspace scope at a glance."
          icon={LayoutDashboard}
        />
        <CrmSectionTabs />
        <CrmOverview />
      </div>
    </RequirePermission>
  );
}
