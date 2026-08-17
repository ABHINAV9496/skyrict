import { JournalEntryDetail } from "@/features/finance/journal-entry-detail";

export default async function FinanceJournalEntryDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <JournalEntryDetail entryId={id} />;
}
