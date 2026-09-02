import { LayoutDashboard } from "lucide-react";

import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CrmOverview } from "@/components/dashboard/erp/crm/crm-overview";

export default function CrmOverviewPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-5">
        <div>
          <div className="flex items-center gap-2">
            <LayoutDashboard className="size-5 text-primary" />
            <h1 className="font-display text-xl font-bold tracking-tight text-foreground">
              CRM Overview
            </h1>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Pipeline, customers, leads, and follow-ups at a glance.
          </p>
        </div>
        <CrmOverview />
      </div>
    </RequirePermission>
  );
}
