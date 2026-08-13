import { BarChart3 } from "lucide-react";

import { ErpReportsKpis } from "@/components/dashboard/erp-reports-kpis";
import { PageHeader } from "@/components/dashboard/page-header";

export default function ErpReportsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Cross-department dashboards and exports for your business."
        icon={BarChart3}
      />
      <ErpReportsKpis />
    </div>
  );
}
