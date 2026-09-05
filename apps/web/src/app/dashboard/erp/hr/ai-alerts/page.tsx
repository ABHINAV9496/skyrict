import type { Metadata } from "next";

import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { AiAlertsClient } from "./ai-alerts";

export const metadata: Metadata = {
  title: "AI alerts · HR",
};

export default function AiAlertsPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.ai.read">
      <AiAlertsClient />
    </ModuleAccessBoundary>
  );
}