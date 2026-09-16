"use client";

import { useState } from "react";

import { FinanceAccounts } from "@/features/finance/accounts";
import { FinanceAssets } from "@/features/finance/assets";
import { cn } from "@/lib/utils";

type LedgerTab = "accounts" | "assets";

const LEDGER_TABS: { key: LedgerTab; label: string }[] = [
    { key: "accounts", label: "Accounts" },
    { key: "assets", label: "Fixed Assets" },
];

function initialTab(): LedgerTab {
    if (typeof window === "undefined") return "accounts";
    const hash = window.location.hash.replace("#", "") as LedgerTab;
    return LEDGER_TABS.some((tab) => tab.key === hash) ? hash : "accounts";
}

export function FinanceLedger() {
    const [tab, setTab] = useState<LedgerTab>(initialTab);

    function selectTab(next: LedgerTab) {
        setTab(next);
        if (typeof window !== "undefined") {
            window.location.hash = next;
        }
    }

    return (
        <div className="space-y-6">
            <div
                role="tablist"
                aria-label="Ledger"
                className="inline-flex rounded-lg border border-border bg-card p-0.5"
            >
                {LEDGER_TABS.map((item) => (
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

            {tab === "accounts" ? <FinanceAccounts /> : null}
            {tab === "assets" ? <FinanceAssets /> : null}
        </div>
    );
}
