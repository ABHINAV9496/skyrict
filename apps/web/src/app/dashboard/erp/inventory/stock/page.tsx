import { Layers } from "lucide-react";

import { InventoryNav } from "@/components/dashboard/erp/inventory/inventory-nav";
import { StockClient } from "@/components/dashboard/erp/inventory/stock";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryStockPage() {
    return (
        <div className="space-y-6">
            <PageHeader
                title="Stock levels"
                description="Current on-hand and reserved counts per product and warehouse."
                icon={Layers}
            />
            <InventoryNav />
            <StockClient />
        </div>
    );
}
