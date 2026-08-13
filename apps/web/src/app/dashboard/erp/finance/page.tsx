import { Wallet } from "lucide-react";

import { ErpModuleTable } from "@/components/dashboard/erp-module-table";
import { PageHeader } from "@/components/dashboard/page-header";

export default function ErpFinancePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Finance"
        description="Cash in and out — invoices, payroll, procurement, and facility costs."
        icon={Wallet}
      />
      <ErpModuleTable module="finance" />
    </div>
  );
}
