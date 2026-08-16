import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { CompensationClient } from "./compensation";

export default function CompensationPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.read">
      <CompensationClient />
    </ModuleAccessBoundary>
  );
}
