import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { DepartmentsClient } from "./departments";

export default function DepartmentsPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <DepartmentsClient />
    </ModuleAccessBoundary>
  );
}
