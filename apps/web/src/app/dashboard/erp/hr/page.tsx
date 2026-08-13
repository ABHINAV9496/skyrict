import { Users } from "lucide-react";

import { ErpModuleTable } from "@/components/dashboard/erp-module-table";
import { PageHeader } from "@/components/dashboard/page-header";

export default function ErpHrPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="HR"
        description="The people behind the business — roles, departments, and tenure."
        icon={Users}
      />
      <ErpModuleTable module="hr" />
    </div>
  );
}
