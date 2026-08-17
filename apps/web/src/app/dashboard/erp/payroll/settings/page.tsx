import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { PayrollSettingsClient } from "./settings";

export default function PayrollSettingsPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.read">
      <PayrollSettingsClient />
    </ModuleAccessBoundary>
  );
}
