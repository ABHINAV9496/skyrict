import type { Metadata } from "next";

import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { AutomationClient } from "./automation";

export const metadata: Metadata = {
  title: "Payroll automation",
};

export default function AutomationPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.payroll.ai.read">
      <AutomationClient />
    </ModuleAccessBoundary>
  );
}