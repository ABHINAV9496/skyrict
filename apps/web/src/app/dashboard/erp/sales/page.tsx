import { ShoppingCart } from "lucide-react";

import { ErpModuleTable } from "@/components/dashboard/erp-module-table";
import { PageHeader } from "@/components/dashboard/page-header";

export default function ErpSalesPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Sales"
        description="Orders, invoices, and the deals flowing through the pipeline."
        icon={ShoppingCart}
      />
      <ErpModuleTable module="sales" />
    </div>
  );
}
