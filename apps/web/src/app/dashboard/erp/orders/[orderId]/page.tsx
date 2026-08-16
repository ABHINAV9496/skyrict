import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { OrderDetail } from "@/components/dashboard/erp/sales/order-detail";

export default async function OrderDetailPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  const { orderId } = await params;
  return (
    <RequirePermission permission="erp.sales.read">
      <OrderDetail orderId={orderId} />
    </RequirePermission>
  );
}
