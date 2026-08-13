import { Suspense } from "react";

import { IntelligenceResults } from "@/components/dashboard/intelligence-results";

export default function IntelligenceResultsPage() {
  return (
    <Suspense fallback={<p className="text-center text-sm text-muted-foreground">Loading…</p>}>
      <IntelligenceResults />
    </Suspense>
  );
}
