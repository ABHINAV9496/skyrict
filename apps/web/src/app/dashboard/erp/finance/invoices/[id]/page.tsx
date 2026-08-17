import { InvoiceDetail } from "@/features/finance/invoice-detail";

export default async function FinanceInvoiceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <InvoiceDetail invoiceId={id} />;
}
