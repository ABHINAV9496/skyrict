import { TrendingUp } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { OpportunitiesBoard } from "@/components/dashboard/erp/crm/opportunities-board";

export default function CrmOpportunitiesPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="Opportunities"
          description="Deals move forward one stage at a time — winning one creates the customer automatically."
          icon={TrendingUp}
        />
        <OpportunitiesBoard />
      </div>
    </RequirePermission>
  );
}
