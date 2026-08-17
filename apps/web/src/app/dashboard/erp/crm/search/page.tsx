import { Search } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CrmSectionTabs } from "@/components/dashboard/erp/crm/crm-section-tabs";
import { CrmSearch } from "@/components/dashboard/erp/crm/crm-search";

export default function CrmSearchPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="Search"
          description="Find any lead, opportunity, customer, or contact across the CRM workspace."
          icon={Search}
        />
        <CrmSectionTabs />
        <CrmSearch />
      </div>
    </RequirePermission>
  );
}
