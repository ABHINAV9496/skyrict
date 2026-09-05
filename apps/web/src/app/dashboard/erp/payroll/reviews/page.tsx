import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { PayslipReviewsClient } from "./reviews";

export default async function PayslipReviewsPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.approve">
      <PayslipReviewsClient />
    </ModuleAccessBoundary>
  );
}