import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { LeaveClient } from "./leave";

export default function LeavePage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <LeaveClient />
    </ModuleAccessBoundary>
  );
}
