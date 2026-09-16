import { redirect } from "next/navigation";

export default function FinanceBudgetsPage() {
    redirect("/dashboard/erp/finance/controls#budgets");
}