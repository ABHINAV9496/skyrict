import { LeavePortal } from "./leave-portal";

/**
 * The employee self-service leave portal. Access is enforced server-side by
 * the /api/v1/portal/* permission gate (erp.leave.self + a linked employee);
 * the client renders the backend's error message when access is missing.
 */
export default function LeavePortalPage() {
  return <LeavePortal />;
}
