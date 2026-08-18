import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { LeadDetail } from "@/components/dashboard/erp/crm/lead-detail";

export default async function LeadDetailPage({
  params,
}: {
  params: Promise<{ leadId: string }>;
}) {
  const { leadId } = await params;
  return (
    <RequirePermission permission="erp.crm.read">
      <LeadDetail leadId={leadId} />
    </RequirePermission>
  );
}
