import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { EmployeeDetailClient } from "./employee-detail";

export default async function EmployeeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <EmployeeDetailClient employeeId={id} />
    </ModuleAccessBoundary>
  );
}
