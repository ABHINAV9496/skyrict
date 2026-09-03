import type { Metadata } from "next";

import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { PayrollAnomaliesClient } from "./payroll-anomalies";

export const metadata: Metadata = {
  title: "Payroll anomalies",
};

export default function PayrollAnomaliesPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.ai.read">
      <PayrollAnomaliesClient />
    </ModuleAccessBoundary>
  );
}