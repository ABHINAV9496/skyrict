import { Package } from "lucide-react";

import { InventoryOverview } from "@/components/dashboard/erp/inventory/inventory-overview";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryPage() {
    return (
        <div className="space-y-8">
            <PageHeader
                title="Inventory"
                description="Stock levels, reorder points, and what is moving across warehouses."
                icon={Package}
            />
            <InventoryOverview />
        </div>
    );
}
