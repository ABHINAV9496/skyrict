import { Receipt } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { PayrollOverview } from "./payroll-overview";

export default function PayrollHomePage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.read">
      <div className="space-y-6">
        <PageHeader
          title="Payroll"
          description="Pay everyone on time runs, compensation, and rules."
          icon={Receipt}
        />
        <PayrollOverview />
      </div>
    </ModuleAccessBoundary>
  );
}
