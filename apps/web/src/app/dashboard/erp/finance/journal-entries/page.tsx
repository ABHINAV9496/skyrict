import { Suspense } from "react";
import { NotebookPen } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { FinanceJournalEntries } from "@/features/finance/journal-entries";

export default function FinanceJournalEntriesPage() {
    return (
        <Suspense
            fallback={
                <div className="space-y-6">
                    <PageHeader
                        title="Journal Entries"
                        description="The general ledger - every debit and credit the business posts."
                        icon={NotebookPen}
                    />
                    <TableSkeleton rows={6} />
                </div>
            }
        >
            <FinanceJournalEntries />
        </Suspense>
    );
}