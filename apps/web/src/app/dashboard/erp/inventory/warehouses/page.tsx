import { Warehouse } from "lucide-react";

import { InventoryNav } from "@/components/dashboard/erp/inventory/inventory-nav";
import { WarehousesClient } from "@/components/dashboard/erp/inventory/warehouses";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryWarehousesPage() {
    return (
        <div className="space-y-6">
            <PageHeader
                title="Warehouses"
                description="Where stock lives — add and manage storage locations."
                icon={Warehouse}
            />
            <InventoryNav />
            <WarehousesClient />
        </div>
    );
}
