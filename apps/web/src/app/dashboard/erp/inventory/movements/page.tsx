import { ArrowLeftRight } from "lucide-react";

import { MovementsClient } from "@/components/dashboard/erp/inventory/movements";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryMovementsPage() {
    return (
        <div className="space-y-6">
            <PageHeader
                title="Movements"
                description="The immutable stock ledger every change, newest first."
                icon={ArrowLeftRight}
            />
            <MovementsClient />
        </div>
    );
}
