import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { EmployeesClient, type EmployeeListView } from "./employees";

export default async function EmployeesPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const { view } = await searchParams;
  const initialView: EmployeeListView = view === "terminated" ? "terminated" : "active";

  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <EmployeesClient initialView={initialView} />
    </ModuleAccessBoundary>
  );
}
