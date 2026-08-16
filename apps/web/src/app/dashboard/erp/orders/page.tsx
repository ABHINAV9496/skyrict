import { ShoppingCart } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { OrdersTable } from "@/components/dashboard/erp/sales/orders-table";

export default function SalesOrdersPage() {
  return (
    <RequirePermission permission="erp.sales.read">
      <div className="space-y-6">
        <PageHeader
          title="Orders"
          description="Draft, confirm, fulfil, and cancel sales orders. Confirmation runs the customer's credit check."
          icon={ShoppingCart}
        />
        <OrdersTable />
      </div>
    </RequirePermission>
  );
}
