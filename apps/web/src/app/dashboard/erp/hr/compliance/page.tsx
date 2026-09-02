import type { Metadata } from "next";

import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { ComplianceClient } from "./compliance";

export const metadata: Metadata = {
  title: "Compliance · HR",
};

export default function CompliancePage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.ai.read">
      <ComplianceClient />
    </ModuleAccessBoundary>
  );
}
