import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { CustomerDetail } from "@/components/dashboard/erp/crm/customer-detail";

export default async function CustomerDetailPage({
  params,
}: {
  params: Promise<{ customerId: string }>;
}) {
  const { customerId } = await params;
  return (
    <RequirePermission permission="erp.crm.read">
      <CustomerDetail customerId={customerId} />
    </RequirePermission>
  );
}
