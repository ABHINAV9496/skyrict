import { Suspense } from "react";

import { PlansPage } from "@/features/billing/plans-page";
import { SettingsSkeleton } from "@/components/ui/page-skeletons";

export default function BillingSettingsPage() {
    return (
        <Suspense fallback={<SettingsSkeleton />}>
            <PlansPage />
        </Suspense>
    );
}
