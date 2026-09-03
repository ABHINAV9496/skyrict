import { Users } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CustomersTable } from "@/components/dashboard/erp/crm/customers-table";

export default function CrmCustomersPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="Customers"
          description="Every account your business sells to, including the ones created from won opportunities."
          icon={Users}
        />
        <CustomersTable />
      </div>
    </RequirePermission>
  );
}
