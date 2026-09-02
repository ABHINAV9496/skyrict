import { CalendarCheck2 } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { ActivitiesTable } from "@/components/dashboard/erp/crm/activities-table";

export default function CrmActivitiesPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="Activities"
          description="Every call, meeting, email, and follow-up — filter by what needs attention today."
          icon={CalendarCheck2}
        />
        <ActivitiesTable />
      </div>
    </RequirePermission>
  );
}
