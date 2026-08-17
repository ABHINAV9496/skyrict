import type { LeaveRequestStatus } from "@/lib/api/hr-api";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { LeaveClient } from "./leave";

const VALID_STATUSES: LeaveRequestStatus[] = ["pending", "approved", "rejected", "cancelled"];

export default async function LeavePage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const initialStatus = VALID_STATUSES.includes(status as LeaveRequestStatus)
    ? (status as LeaveRequestStatus)
    : undefined;

  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <LeaveClient initialStatus={initialStatus} />
    </ModuleAccessBoundary>
  );
}
