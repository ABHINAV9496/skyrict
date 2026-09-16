"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
    Calculator,
    CircleCheck,
    LoaderCircle,
    Package,
    Plus,
    RefreshCw,
} from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
    createAsset,
    disposeAsset,
    listAssets,
    listDepreciationEntries,
    runDepreciation,
    type AssetStatus,
    type DepreciationRunResult,
    type FixedAsset,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney, sumMoney } from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import { StatusBadge } from "@/features/finance/components/status-badge";
import {
    FinanceEmptyState,
    FinanceErrorState,
} from "@/features/finance/components/state-cards";
import { TableToolbar } from "@/features/finance/components/table-toolbar";

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; assets: FixedAsset[] };

const assetTone = (status: AssetStatus) =>
    status === "active"
        ? "success"
        : status === "disposed"
          ? "muted"
          : "warning";

const assetLabel = (status: AssetStatus) => status.replace("_", " ");

function currentMonth(): string {
    return new Date().toISOString().slice(0, 7);
}

function CreateAssetDialog({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onCreated: () => void;
}) {
    const setOpen = onOpenChange;
    const [name, setName] = useState("");
    const [category, setCategory] = useState("");
    const [cost, setCost] = useState("");
    const [acquisitionDate, setAcquisitionDate] = useState(
        new Date().toISOString().slice(0, 10),
    );
    const [usefulLife, setUsefulLife] = useState("5");
    const [salvageValue, setSalvageValue] = useState("0");
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    async function submit() {
        const costValue = Number(cost);
        const lifeValue = Number(usefulLife);
        const salvageValueNumber = Number(salvageValue);
        if (
            !name.trim() ||
            !Number.isFinite(costValue) ||
            costValue <= 0 ||
            !Number.isInteger(lifeValue) ||
            lifeValue < 1 ||
            lifeValue > 100
        ) {
            setSubmitError(
                "Enter a name, a positive cost, and a useful life of 1-100 years.",
            );
            return;
        }
        setSubmitError(null);
        setSubmitting(true);
        try {
            await createAsset({
                name: name.trim(),
                cost: costValue,
                acquisition_date: acquisitionDate,
                useful_life_years: lifeValue,
                category: category.trim() || null,
                salvage_value: Number.isFinite(salvageValueNumber)
                    ? salvageValueNumber
                    : 0,
            });
            setOpen(false);
            onCreated();
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The asset could not be created.",
            );
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogTrigger asChild>
                <Button>
                    <Plus aria-hidden="true" className="size-4" />
                    New asset
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-xl">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Package aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>New fixed asset</DialogTitle>
                        <DialogDescription>
                            A capitalized asset is depreciated monthly with
                            straight-line method once depreciation runs for its
                            acquisition period.
                        </DialogDescription>
                    </DialogHeader>
                </div>
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                    className="space-y-4"
                >
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="asset-name">Name</Label>
                            <Input
                                id="asset-name"
                                value={name}
                                onChange={(event) =>
                                    setName(event.target.value)
                                }
                                placeholder="e.g. Delivery truck"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="asset-category">Category</Label>
                            <Input
                                id="asset-category"
                                value={category}
                                onChange={(event) =>
                                    setCategory(event.target.value)
                                }
                                placeholder="e.g. Vehicles"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="asset-cost">Cost</Label>
                            <Input
                                id="asset-cost"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                value={cost}
                                onChange={(event) =>
                                    setCost(event.target.value)
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="asset-acquired">Acquired on</Label>
                            <Input
                                id="asset-acquired"
                                type="date"
                                value={acquisitionDate}
                                onChange={(event) =>
                                    setAcquisitionDate(event.target.value)
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="asset-life">
                                Useful life (years)
                            </Label>
                            <Input
                                id="asset-life"
                                type="number"
                                inputMode="numeric"
                                min="1"
                                max="100"
                                value={usefulLife}
                                onChange={(event) =>
                                    setUsefulLife(event.target.value)
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="asset-salvage">Salvage value</Label>
                            <Input
                                id="asset-salvage"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                value={salvageValue}
                                onChange={(event) =>
                                    setSalvageValue(event.target.value)
                                }
                            />
                        </div>
                    </div>
                    {submitError ? (
                        <p
                            role="alert"
                            className="text-sm font-medium text-destructive"
                        >
                            {submitError}
                        </p>
                    ) : null}
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => setOpen(false)}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting}>
                            {submitting ? (
                                <LoaderCircle
                                    aria-hidden="true"
                                    className="size-4 animate-spin"
                                />
                            ) : null}
                            Save asset
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function DisposeAssetDialog({
    asset,
    onDisposed,
    trigger,
}: {
    asset: FixedAsset;
    onDisposed: () => void;
    trigger: ReactNode;
}) {
    const [open, setOpen] = useState(false);
    const [disposedOn, setDisposedOn] = useState(
        new Date().toISOString().slice(0, 10),
    );
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);

    async function submit() {
        setSubmitError(null);
        setSubmitting(true);
        try {
            await disposeAsset(asset.id, disposedOn);
            setOpen(false);
            onDisposed();
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The asset could not be disposed.",
            );
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>{trigger}</DialogTrigger>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>Dispose {asset.name}</DialogTitle>
                    <DialogDescription>
                        The asset is written off from the effective date and
                        stops accruing depreciation.
                    </DialogDescription>
                </DialogHeader>
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                    className="space-y-4"
                >
                    <div className="space-y-1.5">
                        <Label htmlFor="dispose-date">Disposed on</Label>
                        <Input
                            id="dispose-date"
                            type="date"
                            value={disposedOn}
                            onChange={(event) =>
                                setDisposedOn(event.target.value)
                            }
                        />
                    </div>
                    {submitError ? (
                        <p
                            role="alert"
                            className="text-sm font-medium text-destructive"
                        >
                            {submitError}
                        </p>
                    ) : null}
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => setOpen(false)}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting}>
                            {submitting ? (
                                <LoaderCircle
                                    aria-hidden="true"
                                    className="size-4 animate-spin"
                                />
                            ) : null}
                            Dispose asset
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

const columns: (onDisposed: () => void) => FinanceColumn<FixedAsset>[] = (
    onDisposed,
) => [
    { label: "Asset", render: (asset) => asset.name },
    { label: "Category", render: (asset) => asset.category ?? "-" },
    {
        label: "Cost",
        align: "right",
        render: (asset) => (
            <span className="tabular-nums">{formatMoney(asset.cost)}</span>
        ),
    },
    {
        label: "Accumulated",
        align: "right",
        render: (asset) => (
            <span className="tabular-nums text-muted-foreground">
                {formatMoney(asset.accumulated_depreciation)}
            </span>
        ),
    },
    {
        label: "Net book value",
        align: "right",
        render: (asset) => (
            <span className="font-medium tabular-nums">
                {formatMoney(asset.net_book_value)}
            </span>
        ),
    },
    {
        label: "Life",
        align: "right",
        render: (asset) => (
            <span className="tabular-nums">{asset.useful_life_years}y</span>
        ),
    },
    {
        label: "Status",
        render: (asset) => (
            <StatusBadge tone={assetTone(asset.status)}>
                {assetLabel(asset.status)}
            </StatusBadge>
        ),
    },
    {
        label: "",
        align: "right",
        render: (asset) =>
            asset.status === "disposed" ? null : (
                <DisposeAssetDialog
                    asset={asset}
                    onDisposed={onDisposed}
                    trigger={
                        <Button variant="outline" size="sm">
                            Dispose
                        </Button>
                    }
                />
            ),
    },
];

export function FinanceAssets() {
    const { permissions } = useModuleAccess();
    const canWrite = hasPermission(permissions, "erp.asset.write");
    const canRun = hasPermission(permissions, "erp.asset.run");
    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [period, setPeriod] = useState(currentMonth());
    const [runResult, setRunResult] = useState<DepreciationRunResult | null>(
        null,
    );
    const [runError, setRunError] = useState<string | null>(null);
    const [running, setRunning] = useState(false);
    const [entries, setEntries] = useState<Awaited<
        ReturnType<typeof listDepreciationEntries>
    > | null>(null);
    const [query, setQuery] = useState("");
    const [statusTab, setStatusTab] = useState("all");
    const [createOpen, setCreateOpen] = useState(false);

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const assets = await listAssets();
            setStatus({ state: "ready", assets });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load fixed assets.",
            });
        }
    }, []);

    const loadEntries = useCallback(async () => {
        try {
            setEntries(await listDepreciationEntries(period));
        } catch {
            setEntries(null);
        }
    }, [period]);

    useEffect(() => {
        void load();
    }, [load]);

    useEffect(() => {
        void loadEntries();
    }, [loadEntries]);

    async function run() {
        setRunError(null);
        setRunResult(null);
        setRunning(true);
        try {
            setRunResult(await runDepreciation(period));
            await loadEntries();
            await load();
        } catch (error) {
            setRunError(
                error instanceof ApiError
                    ? error.message
                    : "Depreciation could not be run.",
            );
        } finally {
            setRunning(false);
        }
    }

    if (status.state === "loading") {
        return (
            <div className="space-y-6">
                <PageHeader
                    title="Fixed Assets"
                    description="Capitalized assets and their monthly depreciation accruals."
                    icon={Package}
                />
                <TableSkeleton rows={6} />
            </div>
        );
    }

    if (status.state === "error") {
        return (
            <div className="space-y-6">
                <PageHeader
                    title="Fixed Assets"
                    description="Capitalized assets and their monthly depreciation accruals."
                    icon={Package}
                />
                <FinanceErrorState
                    message={status.message}
                    onRetry={() => void load()}
                />
            </div>
        );
    }

    const needle = query.trim().toLowerCase();
    const visibleAssets = status.assets.filter((asset) => {
        if (statusTab !== "all" && asset.status !== statusTab) return false;
        if (!needle) return true;
        return (
            asset.name.toLowerCase().includes(needle) ||
            (asset.category ?? "").toLowerCase().includes(needle)
        );
    });

    const totalNbv = sumMoney(
        status.assets
            .filter((asset) => asset.status === "active")
            .map((asset) => asset.net_book_value),
    );

    const entryColumns: FinanceColumn<NonNullable<typeof entries>[number]>[] = [
        { label: "Period", render: (entry) => entry.period },
        {
            label: "Amount",
            align: "right",
            render: (entry) => (
                <span className="tabular-nums">
                    {formatMoney(entry.amount)}
                </span>
            ),
        },
        {
            label: "Status",
            render: (entry) => (
                <StatusBadge
                    tone={entry.journal_entry_id ? "success" : "muted"}
                >
                    {entry.journal_entry_id ? "JE created" : "SKIPPED"}
                </StatusBadge>
            ),
        },
        { label: "Created", render: (entry) => formatDate(entry.created_at) },
    ];

    return (
        <div className="space-y-6">
            <PageHeader
                title="Fixed Assets"
                description="Capitalized assets and their monthly depreciation accruals."
                icon={Package}
            />
            <TableToolbar
                searchPlaceholder="Search assets…"
                searchValue={query}
                onSearchChange={setQuery}
                tabs={[
                    { key: "all", label: "All", count: status.assets.length },
                    {
                        key: "active",
                        label: "Active",
                        count: status.assets.filter(
                            (a) => a.status === "active",
                        ).length,
                    },
                    {
                        key: "fully_depreciated",
                        label: "Fully depreciated",
                        count: status.assets.filter(
                            (a) => a.status === "fully_depreciated",
                        ).length,
                    },
                    {
                        key: "disposed",
                        label: "Disposed",
                        count: status.assets.filter(
                            (a) => a.status === "disposed",
                        ).length,
                    },
                ]}
                activeTab={statusTab}
                onTabChange={setStatusTab}
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        {canRun ? (
                            <span className="inline-flex items-center gap-2">
                                <Input
                                    aria-label="Depreciation period"
                                    type="month"
                                    value={period}
                                    onChange={(event) =>
                                        setPeriod(event.target.value)
                                    }
                                    className="w-40"
                                />
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={running}
                                    onClick={() => void run()}
                                >
                                    {running ? (
                                        <LoaderCircle
                                            aria-hidden="true"
                                            className="size-3.5 animate-spin"
                                        />
                                    ) : (
                                        <Calculator
                                            aria-hidden="true"
                                            className="size-3.5"
                                        />
                                    )}
                                    Run depreciation
                                </Button>
                            </span>
                        ) : null}
                        {canWrite ? (
                            <CreateAssetDialog
                                open={createOpen}
                                onOpenChange={setCreateOpen}
                                onCreated={() => void load()}
                            />
                        ) : null}
                    </div>
                }
            />

            {runResult ? (
                <div className="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm">
                    <CircleCheck
                        aria-hidden="true"
                        className="size-4 shrink-0 text-emerald-500"
                    />
                    <span className="text-foreground">
                        Depreciation for {runResult.period}:{" "}
                        <span className="font-semibold tabular-nums">
                            {formatMoney(runResult.total_amount)}
                        </span>{" "}
                        posted across {runResult.entries_created} entries (
                        {runResult.entries_skipped} already accrued).
                    </span>
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="ml-auto"
                        onClick={() => setRunResult(null)}
                    >
                        Dismiss
                    </Button>
                </div>
            ) : null}
            {runError ? (
                <p
                    role="alert"
                    className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm font-medium text-destructive"
                >
                    {runError}
                </p>
            ) : null}

            {visibleAssets.length === 0 ? (
                <FinanceEmptyState
                    icon={Package}
                    title="No fixed assets yet"
                    description="Add a capitalized asset to start accruing monthly depreciation."
                />
            ) : (
                <FinanceTable
                    columns={columns(load)}
                    rows={visibleAssets}
                    getKey={(asset) => asset.id}
                    footer={
                        <span className="flex justify-between gap-4">
                            <span>
                                {visibleAssets.length} of {status.assets.length}{" "}
                                assets
                            </span>
                            <span className="tabular-nums">
                                Active net book value {formatMoney(totalNbv)}
                            </span>
                        </span>
                    }
                />
            )}

            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <h2 className="font-display text-sm font-semibold text-foreground">
                        Depreciation entries
                    </h2>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void loadEntries()}
                    >
                        <RefreshCw aria-hidden="true" className="size-3.5" />
                        Refresh
                    </Button>
                </div>
                {entries && entries.length === 0 ? (
                    <FinanceEmptyState
                        icon={Calculator}
                        title="No depreciation entries"
                        description="Run depreciation for a period to accrue monthly amounts."
                    />
                ) : (
                    <FinanceTable
                        columns={entryColumns}
                        rows={entries ?? []}
                        getKey={(entry) => entry.id}
                        emptyMessage="No depreciation entries for this period."
                    />
                )}
            </div>
        </div>
    );
}
