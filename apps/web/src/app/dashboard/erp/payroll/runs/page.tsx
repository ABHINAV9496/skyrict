import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { RunsClient } from "./runs";

export default function RunsPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.read">
      <RunsClient />
    </ModuleAccessBoundary>
  );
}
