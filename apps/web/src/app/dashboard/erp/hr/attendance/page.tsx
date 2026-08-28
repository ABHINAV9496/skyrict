import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { AttendanceClient } from "./attendance";

export default async function AttendancePage({
  searchParams,
}: {
  searchParams: Promise<{ employee?: string }>;
}) {
  const { employee } = await searchParams;

  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <AttendanceClient initialEmployeeId={employee ?? null} />
    </ModuleAccessBoundary>
  );
}
