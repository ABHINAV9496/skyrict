import { Package } from "lucide-react";

import { ErpModuleTable } from "@/components/dashboard/erp/erp-module-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Inventory"
        description="Stock levels, reorder points, and what is moving across warehouses."
        icon={Package}
      />
      <ErpModuleTable module="inventory" />
    </div>
  );
}
