import { Contact } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CrmSectionTabs } from "@/components/dashboard/erp/crm/crm-section-tabs";
import { LeadsTable } from "@/components/dashboard/erp/crm/leads-table";

export default function CrmLeadsPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="Leads"
          description="Inbound inquiries. Qualify them to build pipeline, or disqualify to keep the list clean."
          icon={Contact}
        />
        <CrmSectionTabs />
        <LeadsTable />
      </div>
    </RequirePermission>
  );
}
