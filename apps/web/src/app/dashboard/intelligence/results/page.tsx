import { Suspense } from "react";

import { IntelligenceResults } from "@/components/dashboard/intelligence/intelligence-results";
import { IntelligenceSearch } from "@/components/dashboard/intelligence/intelligence-search";
import { IntelligenceResultsListSkeleton } from "@/components/ui/page-skeletons";
import { Skeleton } from "@/components/ui/skeleton";

export default function IntelligenceResultsPage() {
  return (
    <div className="space-y-6">
      <Suspense
        fallback={
          <div className="mx-auto w-full max-w-2xl">
            <Skeleton className="h-10 w-full rounded-full" />
          </div>
        }
      >
        <IntelligenceSearch variant="inline" />
      </Suspense>
      <Suspense fallback={<IntelligenceResultsListSkeleton />}>
        <IntelligenceResults />
      </Suspense>
    </div>
  );
}
