import type { Metadata } from "next";

import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { AttritionClient } from "./attrition";

export const metadata: Metadata = {
  title: "Attrition risk · HR",
};

export default function AttritionPage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.ai.read">
      <AttritionClient />
    </ModuleAccessBoundary>
  );
}