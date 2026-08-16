import { Users } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { HrOverview } from "./hr-overview";
import { HrSetup } from "./hr-setup";

export default function HrHomePage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <div className="space-y-6">
        <PageHeader
          title="HR"
          description="The people behind the business — employees, departments, and leave."
          icon={Users}
        />
        <HrSetup />
        <HrOverview />
      </div>
    </ModuleAccessBoundary>
  );
}
