import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { OpportunityDetail } from "@/components/dashboard/erp/crm/opportunity-detail";

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ opportunityId: string }>;
}) {
  const { opportunityId } = await params;
  return (
    <RequirePermission permission="erp.crm.read">
      <OpportunityDetail opportunityId={opportunityId} />
    </RequirePermission>
  );
}
