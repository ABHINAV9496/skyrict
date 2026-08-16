import { BellRing } from "lucide-react";

import { AlertsClient } from "@/components/dashboard/erp/inventory/alerts";
import { InventoryNav } from "@/components/dashboard/erp/inventory/inventory-nav";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryAlertsPage() {
    return (
        <div className="space-y-6">
            <PageHeader
                title="Reorder alerts"
                description="Products at or below their reorder point that need attention."
                icon={BellRing}
            />
            <InventoryNav />
            <AlertsClient />
        </div>
    );
}
