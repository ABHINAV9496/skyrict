import type { Metadata } from "next";

import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { PlanningStudio } from "./planning-studio";

export const metadata: Metadata = {
    title: "Planning studio",
};

export default function PlanningStudioPage() {
    return (
        <ModuleAccessBoundary
            module="erp"
            permission="erp.hr.ai.planning"
        >
            <PlanningStudio />
        </ModuleAccessBoundary>
    );
}