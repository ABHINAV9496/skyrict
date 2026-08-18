import { Package } from "lucide-react";

import { ProductsClient } from "@/components/dashboard/erp/inventory/products";
import { PageHeader } from "@/components/dashboard/shared/page-header";

export default function ErpInventoryProductsPage() {
    return (
        <div className="space-y-6">
            <PageHeader
                title="Products"
                description="The catalog of what you track stock for, with costs and reorder points."
                icon={Package}
            />
            <ProductsClient />
        </div>
    );
}
