import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { RunDetailClient } from "./run-detail";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.read">
      <RunDetailClient runId={id} />
    </ModuleAccessBoundary>
  );
}
