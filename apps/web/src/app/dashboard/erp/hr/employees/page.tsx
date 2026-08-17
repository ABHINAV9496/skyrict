import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { EmployeesClient } from "./employees";

export default function EmployeesPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <EmployeesClient />
    </ModuleAccessBoundary>
  );
}
