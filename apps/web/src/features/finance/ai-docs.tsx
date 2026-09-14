"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
    BookOpen,
    Download,
    FileCheck2,
    FileText,
    LoaderCircle,
    MessageCircleQuestion,
    Plus,
    Search,
    Sparkles,
    X,
} from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
    approveFinanceDoc,
    approveTaxSummary,
    askFinanceDocs,
    downloadFinanceDoc,
    generateFinanceDoc,
    generateTaxSummary,
    getBalanceSheet,
    getProfitAndLoss,
    listFinanceDocs,
    listFiscalPeriods,
    listTaxSummaries,
    narrateFinanceAudit,
    rejectTaxSummary,
    type AiDoc,
    type AiDocAction,
    type AuditNarration,
    type DocQaAnswer,
    type FiscalPeriod,
    type TaxSummary,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDateTime, formatMoney } from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { StatusBadge } from "@/features/finance/components/status-badge";
import {
    FinanceEmptyState,
    FinanceErrorState,
} from "@/features/finance/components/state-cards";

// Strip redundant card styling when rendering inside WidgetCard
const NESTED_CARD = "border-0 bg-transparent rounded-none";

// ---------------------------------------------------------------------------
// Shared loading / error primitives for the four widgets
// ---------------------------------------------------------------------------

function WidgetCard({
    icon: Icon,
    title,
    description,
    children,
}: {
    icon: typeof Sparkles;
    title: string;
    description: string;
    children: ReactNode;
}) {
    return (
        <section className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="flex items-start gap-3 border-b border-border/60 px-4 py-4">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon aria-hidden="true" className="size-4" />
                </div>
                <div className="space-y-0.5">
                    <h2 className="font-display text-sm font-semibold text-foreground">
                        {title}
                    </h2>
                    <p className="text-xs text-muted-foreground">
                        {description}
                    </p>
                </div>
            </div>
            <div className="p-4">{children}</div>
        </section>
    );
}

function defaultPeriodId(periods: FiscalPeriod[]): string {
    const closed = [...periods].reverse().find((period) => period.is_closed);
    return (closed ?? periods[0])?.id ?? "";
}

function useBusyError() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    return {
        busy,
        error,
        setBusy,
        setError,
        async run(action: () => Promise<void>) {
            setError(null);
            setBusy(true);
            try {
                await action();
            } catch (caught) {
                setError(
                    caught instanceof ApiError
                        ? caught.message
                        : "The request failed. Please try again.",
                );
            } finally {
                setBusy(false);
            }
        },
    };
}

function ActionButton({
    busy,
    label,
    icon: Icon,
    variant = "outline",
    onClick,
}: {
    busy: boolean;
    label: string;
    icon: typeof Plus;
    variant?: "default" | "outline";
    onClick: () => void;
}) {
    return (
        <Button
            type="button"
            variant={variant}
            size="sm"
            disabled={busy}
            onClick={onClick}
        >
            {busy ? (
                <LoaderCircle
                    aria-hidden="true"
                    className="size-3.5 animate-spin"
                />
            ) : (
                <Icon aria-hidden="true" className="size-3.5" />
            )}
            {label}
        </Button>
    );
}

// ---------------------------------------------------------------------------
// A5: tax summary
// ---------------------------------------------------------------------------

function TaxSummaryWidget({ canApprove }: { canApprove: boolean }) {
    const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
    const [summaries, setSummaries] = useState<TaxSummary[]>([]);
    const [periodId, setPeriodId] = useState("");
    const [generating, setGenerating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loadState, setLoadState] = useState<"loading" | "ready">("loading");

    const load = useCallback(async () => {
        setLoadState("loading");
        try {
            const [periodsData, summariesData] = await Promise.all([
                listFiscalPeriods(),
                listTaxSummaries(),
            ]);
            setPeriods(periodsData);
            setSummaries(summariesData);
            setPeriodId((current) =>
                current && periodsData.some((p) => p.id === current)
                    ? current
                    : defaultPeriodId(periodsData),
            );
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not load tax summaries.",
            );
        } finally {
            setLoadState("ready");
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    async function generate() {
        if (!periodId) return;
        setGenerating(true);
        setError(null);
        try {
            const created = await generateTaxSummary(periodId);
            setSummaries((current) => [created, ...current]);
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not generate the tax summary.",
            );
        } finally {
            setGenerating(false);
        }
    }

    async function setStatus(
        summaryId: string,
        action: (id: string) => Promise<AiDocAction>,
    ) {
        try {
            const result = await action(summaryId);
            setSummaries((current) =>
                current.map((summary) =>
                    summary.id === summaryId
                        ? { ...summary, status: result.status }
                        : summary,
                ),
            );
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not update the tax summary.",
            );
        }
    }

    const columns: FinanceColumn<TaxSummary>[] = [
        { label: "Period", render: (summary) => summary.period_name },
        {
            label: "Categories",
            render: (summary) => summary.categories.length,
        },
        {
            label: "Input tax",
            align: "right",
            render: (summary) => formatMoney(summary.total_input),
        },
        {
            label: "Output tax",
            align: "right",
            render: (summary) => formatMoney(summary.total_output),
        },
        {
            label: "Status",
            render: (summary) =>
                summary.status === "approved" ? (
                    <StatusBadge tone="success">Approved</StatusBadge>
                ) : summary.status === "rejected" ? (
                    <StatusBadge tone="danger">Rejected</StatusBadge>
                ) : (
                    <StatusBadge tone="muted">Draft</StatusBadge>
                ),
        },
        {
            label: "Generated",
            render: (summary) => formatDateTime(summary.created_at),
        },
    ];

    if (loadState === "loading") {
        return (
            <WidgetCard
                icon={FileText}
                title="Tax Summary"
                description="Per-category input/output tax from a fiscal period's posted entries."
            >
                <TableSkeleton rows={3} />
            </WidgetCard>
        );
    }

    const actionColumn: FinanceColumn<TaxSummary> = {
        label: "",
        align: "right",
        render: (summary) =>
            summary.status === "draft" && canApprove ? (
                <div className="flex items-center justify-end gap-1.5">
                    <ActionButton
                        busy={false}
                        label="Approve"
                        icon={FileCheck2}
                        onClick={() =>
                            void setStatus(summary.id, approveTaxSummary)
                        }
                    />
                    <ActionButton
                        busy={false}
                        label="Reject"
                        icon={X}
                        variant="default"
                        onClick={() =>
                            void setStatus(summary.id, rejectTaxSummary)
                        }
                    />
                </div>
            ) : null,
    };

    return (
        <WidgetCard
            icon={FileText}
            title="Tax Summary"
            description="Per-category input/output tax from a fiscal period's posted entries."
        >
            <div className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="tax-period">Fiscal period</Label>
                        <Select
                            value={periodId}
                            onValueChange={setPeriodId}
                            disabled={generating}
                        >
                            <SelectTrigger id="tax-period" className="w-64">
                                <SelectValue placeholder="Select a period" />
                            </SelectTrigger>
                            <SelectContent>
                                {periods.map((period) => (
                                    <SelectItem
                                        key={period.id}
                                        value={period.id}
                                    >
                                        {period.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <ActionButton
                        busy={generating}
                        label="Generate"
                        icon={Sparkles}
                        variant="default"
                        onClick={() => void generate()}
                    />
                </div>

                {error ? (
                    <FinanceErrorState
                        className={NESTED_CARD}
                        message={error}
                    />
                ) : null}

                {summaries.length === 0 ? (
                    <FinanceEmptyState
                        className={NESTED_CARD}
                        icon={FileText}
                        title="No tax summaries yet"
                        description="Generate one for a fiscal period to get per-category tax lines."
                    />
                ) : (
                    <FinanceTable
                        className={NESTED_CARD}
                        columns={[...columns, actionColumn]}
                        rows={summaries}
                        getKey={(summary) => summary.id}
                        subtitle="Latest summaries first"
                        emptyMessage="No summaries yet."
                    />
                )}
            </div>
        </WidgetCard>
    );
}

// ---------------------------------------------------------------------------
// A6: document packs
// ---------------------------------------------------------------------------

function DocPacksWidget({ canApprove }: { canApprove: boolean }) {
    const [docs, setDocs] = useState<AiDoc[]>([]);
    const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
    const [periodId, setPeriodId] = useState("");
    const [docType, setDocType] = useState<"pnl" | "balance_sheet">("pnl");
    const [generating, setGenerating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loadState, setLoadState] = useState<"loading" | "ready">("loading");

    const load = useCallback(async () => {
        setLoadState("loading");
        try {
            const [docsData, periodsData] = await Promise.all([
                listFinanceDocs(),
                listFiscalPeriods(),
            ]);
            setDocs(docsData);
            setPeriods(periodsData);
            setPeriodId((current) =>
                current && periodsData.some((p) => p.id === current)
                    ? current
                    : defaultPeriodId(periodsData),
            );
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not load document packs.",
            );
        } finally {
            setLoadState("ready");
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    async function generate() {
        if (!periodId) return;
        setGenerating(true);
        setError(null);
        try {
            const period = periods.find(
                (candidate) => candidate.id === periodId,
            );
            if (!period) {
                throw new ApiError(400, "Select a fiscal period first.");
            }
            const report = (docType === "pnl"
                ? await getProfitAndLoss(period.start_date, period.end_date)
                : await getBalanceSheet(period.end_date)) as unknown as Record<
                string,
                unknown
            >;
            const snapshot_data: Record<string, unknown> = {
                period: period.name,
                from_date: period.start_date,
                to_date: period.end_date,
                ...report,
            };
            const created = await generateFinanceDoc({
                doc_type: docType,
                snapshot_id: period.id,
                snapshot_data,
            });
            setDocs((current) => [created, ...current]);
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not generate the document pack.",
            );
        } finally {
            setGenerating(false);
        }
    }

    async function download(docId: string) {
        try {
            const response = await downloadFinanceDoc(docId);
            if (!response.ok) {
                throw new ApiError(response.status, "Download failed.");
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = `finance-doc-${docId.slice(0, 8)}.pdf`;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not download the document pack.",
            );
        }
    }

    async function approve(docId: string) {
        try {
            const result = await approveFinanceDoc(docId);
            setDocs((current) =>
                current.map((doc) =>
                    doc.id === docId ? { ...doc, status: result.status } : doc,
                ),
            );
        } catch (caught) {
            setError(
                caught instanceof ApiError
                    ? caught.message
                    : "Could not approve the document pack.",
            );
        }
    }

    const columns: FinanceColumn<AiDoc>[] = [
        {
            label: "Type",
            render: (doc) =>
                doc.doc_type === "pnl" ? "Profit & Loss" : "Balance Sheet",
        },
        {
            label: "Fiscal period",
            render: (doc) =>
                periods.find((period) => period.id === doc.snapshot_id)?.name ??
                "Unknown",
        },
        { label: "Version", render: (doc) => `v${doc.version}` },
        {
            label: "Status",
            render: (doc) =>
                doc.status === "approved" ? (
                    <StatusBadge tone="success">Approved</StatusBadge>
                ) : (
                    <StatusBadge tone="muted">
                        {doc.watermarked ? "Draft · watermarked" : "Draft"}
                    </StatusBadge>
                ),
        },
        {
            label: "Created",
            render: (doc) => formatDateTime(doc.created_at),
        },
        {
            label: "",
            align: "right",
            render: (doc) => (
                <div className="flex items-center justify-end gap-1.5">
                    <ActionButton
                        busy={false}
                        label="Download"
                        icon={Download}
                        onClick={() => void download(doc.id)}
                    />
                    {doc.status === "draft" && canApprove ? (
                        <ActionButton
                            busy={false}
                            label="Approve"
                            icon={FileCheck2}
                            onClick={() => void approve(doc.id)}
                        />
                    ) : null}
                </div>
            ),
        },
    ];

    if (loadState === "loading") {
        return (
            <WidgetCard
                icon={BookOpen}
                title="Document Packs"
                description="PDF packs (P&L / balance sheet) generated as watermarked drafts."
            >
                <TableSkeleton rows={3} />
            </WidgetCard>
        );
    }

    return (
        <WidgetCard
            icon={BookOpen}
            title="Document Packs"
            description="PDF packs (P&L / balance sheet) generated as watermarked drafts."
        >
            <div className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="doc-period">Fiscal period</Label>
                        <Select
                            value={periodId}
                            onValueChange={setPeriodId}
                            disabled={generating}
                        >
                            <SelectTrigger id="doc-period" className="w-64">
                                <SelectValue placeholder="Select a period" />
                            </SelectTrigger>
                            <SelectContent>
                                {periods.map((period) => (
                                    <SelectItem
                                        key={period.id}
                                        value={period.id}
                                    >
                                        {period.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="doc-type">Document type</Label>
                        <Select
                            value={docType}
                            onValueChange={(value) =>
                                setDocType(value as "pnl" | "balance_sheet")
                            }
                            disabled={generating}
                        >
                            <SelectTrigger id="doc-type" className="w-64">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="pnl">
                                    Profit &amp; Loss
                                </SelectItem>
                                <SelectItem value="balance_sheet">
                                    Balance Sheet
                                </SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    <ActionButton
                        busy={generating}
                        label="Generate pack"
                        icon={FileText}
                        variant="default"
                        onClick={() => void generate()}
                    />
                </div>

                {error ? (
                    <FinanceErrorState
                        className={NESTED_CARD}
                        message={error}
                    />
                ) : null}

                {docs.length === 0 ? (
                    <FinanceEmptyState
                        className={NESTED_CARD}
                        icon={BookOpen}
                        title="No document packs yet"
                        description="Generate a P&L or balance sheet PDF to review and approve."
                    />
                ) : (
                    <FinanceTable
                        className={NESTED_CARD}
                        columns={columns}
                        rows={docs}
                        getKey={(doc) => doc.id}
                        subtitle="Latest packs first (approved packs drop their watermark)"
                        emptyMessage="No document packs yet."
                    />
                )}
            </div>
        </WidgetCard>
    );
}

// ---------------------------------------------------------------------------
// A10: audit narration
// ---------------------------------------------------------------------------

function AuditNarrationWidget() {
    const [fromDate, setFromDate] = useState<string | null>(null);
    const [toDate, setToDate] = useState<string | null>(null);
    const [narration, setNarration] = useState<AuditNarration | null>(null);
    const { busy, error, run } = useBusyError();

    async function generate() {
        if (!fromDate || !toDate) return;
        await run(async () => {
            setNarration(
                await narrateFinanceAudit({
                    from_date: fromDate,
                    to_date: toDate,
                }),
            );
        });
    }

    return (
        <WidgetCard
            icon={FileCheck2}
            title="Audit Narration"
            description="A plain-English narrative with risk areas over posted entries in a range."
        >
            <div className="space-y-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="audit-from">From</Label>
                        <DatePicker
                            id="audit-from"
                            value={fromDate}
                            onChange={setFromDate}
                            disabled={busy}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="audit-to">To</Label>
                        <DatePicker
                            id="audit-to"
                            value={toDate}
                            onChange={setToDate}
                            min={fromDate ?? undefined}
                            disabled={busy}
                        />
                    </div>
                    <ActionButton
                        busy={busy}
                        label="Narrate"
                        icon={Sparkles}
                        variant="default"
                        onClick={() => void generate()}
                    />
                </div>

                {error ? (
                    <FinanceErrorState
                        className={NESTED_CARD}
                        message={error}
                    />
                ) : null}

                {narration ? (
                    <div className="space-y-3">
                        <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm leading-relaxed text-foreground">
                            {narration.narration}
                        </p>
                        {narration.risk_areas.length > 0 ? (
                            <div className="space-y-2">
                                <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                                    Risk areas
                                </p>
                                {narration.risk_areas.map((risk, index) => (
                                    <div
                                        key={`${risk.risk_type}-${index}`}
                                        className="flex items-start gap-2.5 rounded-lg border border-border p-3"
                                    >
                                        <span>
                                            {risk.severity === "high" ? (
                                                <StatusBadge tone="danger">
                                                    {risk.severity}
                                                </StatusBadge>
                                            ) : risk.severity === "medium" ? (
                                                <StatusBadge tone="warning">
                                                    {risk.severity}
                                                </StatusBadge>
                                            ) : (
                                                <StatusBadge tone="muted">
                                                    {risk.severity}
                                                </StatusBadge>
                                            )}
                                        </span>
                                        <div className="space-y-0.5">
                                            <p className="text-sm font-medium text-foreground">
                                                {risk.risk_type}
                                            </p>
                                            <p className="text-xs text-muted-foreground">
                                                {risk.description}
                                            </p>
                                            {risk.entry_id ? (
                                                <p className="text-[11px] text-muted-foreground">
                                                    Entry{" "}
                                                    {risk.entry_id.slice(0, 8)}
                                                </p>
                                            ) : null}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : null}
                        {narration.model_used ? (
                            <p className="text-[11px] text-muted-foreground">
                                Model: {narration.model_used}
                            </p>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </WidgetCard>
    );
}

// ---------------------------------------------------------------------------
// A12: document Q&A
// ---------------------------------------------------------------------------

function DocQaWidget() {
    const [question, setQuestion] = useState("");
    const [answer, setAnswer] = useState<DocQaAnswer | null>(null);
    const { busy, error, run, setError } = useBusyError();

    async function ask() {
        const trimmed = question.trim();
        if (trimmed.length < 3) {
            setError("Enter at least 3 characters to ask a question.");
            return;
        }
        await run(async () => {
            setAnswer(await askFinanceDocs(trimmed));
        });
    }

    return (
        <WidgetCard
            icon={MessageCircleQuestion}
            title="Document Q&A"
            description="Ask a question over your finance documents with cited answers."
        >
            <div className="space-y-4">
                <div className="space-y-1.5">
                    <Label htmlFor="qa-question">Question</Label>
                    <Textarea
                        id="qa-question"
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        placeholder="e.g. What are the net payment terms on invoices?"
                        rows={2}
                        disabled={busy}
                    />
                </div>
                <ActionButton
                    busy={busy}
                    label="Ask"
                    icon={Search}
                    variant="default"
                    onClick={() => void ask()}
                />

                {error ? (
                    <FinanceErrorState
                        className={NESTED_CARD}
                        message={error}
                    />
                ) : null}

                {answer ? (
                    <div className="space-y-3">
                        <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm leading-relaxed text-foreground">
                            {answer.answer}
                        </p>
                        {answer.citations.length > 0 ? (
                            <div className="space-y-2">
                                <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                                    Cited sources
                                </p>
                                {answer.citations.map((citation, index) => (
                                    <div
                                        key={`${citation.source_ref}-${index}`}
                                        className="rounded-lg border border-border p-3"
                                    >
                                        <p className="text-xs font-medium text-foreground">
                                            {citation.source_ref}
                                        </p>
                                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                            {citation.chunk_text}
                                        </p>
                                        <p className="mt-1 text-[11px] text-muted-foreground">
                                            Score {citation.score.toFixed(3)}
                                        </p>
                                    </div>
                                ))}
                            </div>
                        ) : null}
                        {answer.model_used ? (
                            <p className="text-[11px] text-muted-foreground">
                                Model: {answer.model_used}
                            </p>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </WidgetCard>
    );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function FinanceAiDocs() {
    const { permissions } = useModuleAccess();
    const canApprove = hasPermission(permissions, "erp.finance.approve");

    return (
        <div className="space-y-6">
            <PageHeader
                title="Document & Tax AI"
                description="AI-generated tax summaries, finance document packs, audit narration, and grounded document Q&A."
                icon={Sparkles}
            />
            <TaxSummaryWidget canApprove={canApprove} />
            <DocPacksWidget canApprove={canApprove} />
            <AuditNarrationWidget />
            <DocQaWidget />
        </div>
    );
}
