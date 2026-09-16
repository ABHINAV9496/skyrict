"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FinanceBudgets } from "@/features/finance/budgets";
import { FinanceExpenses } from "@/features/finance/expenses";
import { FinanceCompliance } from "@/features/finance/compliance";
import { cn } from "@/lib/utils";

type ControlTab = "budgets" | "expenses" | "compliance";

const CONTROL_TABS: { key: ControlTab; label: string }[] = [
    { key: "budgets", label: "Budgets" },
    { key: "expenses", label: "Expense Control" },
    { key: "compliance", label: "Compliance" },
];

function initialTab(): ControlTab {
    if (typeof window === "undefined") return "budgets";
    const hash = window.location.hash.replace("#", "") as ControlTab;
    return CONTROL_TABS.some((tab) => tab.key === hash) ? hash : "budgets";
}

export function FinanceControls() {
    const [tab, setTab] = useState<ControlTab>(initialTab);
    const router = useRouter();

    // Fixed assets moved to the Ledger page (SKY-85 navigation cleanup);
    // redirect the old /finance/controls#assets deep link to keep it working.
    useEffect(() => {
        if (typeof window === "undefined") return;
        if (window.location.hash.replace("#", "") === "assets") {
            router.replace("/dashboard/erp/finance/accounts#assets");
        }
    }, [router]);

    function selectTab(next: ControlTab) {
        setTab(next);
        if (typeof window !== "undefined") {
            window.location.hash = next;
        }
    }

    return (
        <div className="space-y-6">
            <div
                role="tablist"
                aria-label="Planning and policy"
                className="inline-flex rounded-lg border border-border bg-card p-0.5"
            >
                {CONTROL_TABS.map((item) => (
                    <button
                        key={item.key}
                        type="button"
                        role="tab"
                        aria-selected={tab === item.key}
                        onClick={() => selectTab(item.key)}
                        className={cn(
                            "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                            tab === item.key
                                ? "bg-primary text-primary-foreground"
                                : "text-muted-foreground hover:text-foreground",
                        )}
                    >
                        {item.label}
                    </button>
                ))}
            </div>

            {tab === "budgets" ? <FinanceBudgets /> : null}
            {tab === "expenses" ? <FinanceExpenses /> : null}
            {tab === "compliance" ? <FinanceCompliance /> : null}
        </div>
    );
}
