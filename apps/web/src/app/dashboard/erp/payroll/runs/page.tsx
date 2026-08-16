import type { PayrollRunStatus } from "@/lib/api/payroll-api";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { RunsClient } from "./runs";

const VALID_STATUSES: PayrollRunStatus[] = ["draft", "computed", "approved", "paid", "void"];

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const initialStatus = VALID_STATUSES.includes(status as PayrollRunStatus)
    ? (status as PayrollRunStatus)
    : undefined;

  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.read">
      <RunsClient initialStatus={initialStatus} />
    </ModuleAccessBoundary>
  );
}
