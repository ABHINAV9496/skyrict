import { Contact } from "lucide-react";

import { ErpModuleTable } from "@/components/dashboard/erp-module-table";
import { PageHeader } from "@/components/dashboard/page-header";

export default function ErpCrmPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="CRM"
        description="Contacts, deals, and pipelines for every customer relationship."
        icon={Contact}
      />
      <ErpModuleTable module="crm" />
    </div>
  );
}
