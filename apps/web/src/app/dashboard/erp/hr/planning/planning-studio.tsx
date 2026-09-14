"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
    LoaderCircle,
    Plus,
    SlidersHorizontal,
    Trash2,
    TrendingUp,
} from "lucide-react";
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import {
    SearchableSelect,
    type SearchableSelectOption,
} from "@/components/dashboard/shared/searchable-select";
import {
    compareScenarios,
    createScenario,
    getPayrollBase,
    getScenario,
    listScenarios,
    type PayrollBase,
    type Projection,
    type Scenario,
    type ScenarioAction,
    type ScenarioCompareItem,
    type ScenarioListItem,
} from "@/lib/api/hr-planning-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready" };

type Notice = { tone: "success" | "error"; text: string };

const ACTION_TYPES = [
    { value: "salary_merit", label: "Salary merit" },
    { value: "new_hire", label: "New hire" },
    { value: "reduction", label: "Reduction" },
    { value: "benefit_change", label: "Benefit" },
] as const;

type ActionType = (typeof ACTION_TYPES)[number]["value"];

interface DraftAction {
    key: string;
    type: ActionType;
    percent: string;
    effective_month: string;
    employee_id: string;
    first_name: string;
    last_name: string;
    job_title: string;
    hire_date: string;
    monthly_salary: string;
    monthly_benefit_cost: string;
    department_id: string;
    department_name: string;
}

interface CompareSelection {
    id: string;
    name: string;
}

const SERIES_COLORS = ["#0ea5e9", "#8b5cf6", "#f59e0b"];
const BUDGET_COLOR = "#64748b";

const axisTick = {
    fontSize: 11,
    fill: "var(--muted-foreground)",
    fontFamily: "var(--font-sans)",
};

const compactMoneyFormatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 0,
});

function emptyDraftAction(): DraftAction {
    const today = new Date().toISOString().slice(0, 10);
    return {
        key: crypto.randomUUID(),
        type: "salary_merit",
        percent: "",
        effective_month: "1",
        employee_id: "",
        first_name: "",
        last_name: "",
        job_title: "",
        hire_date: today,
        monthly_salary: "",
        monthly_benefit_cost: "",
        department_id: "",
        department_name: "",
    };
}

export function PlanningStudio() {
    const [status, setStatus] = useState<PageStatus>({ state: "loading" });
    const [base, setBase] = useState<PayrollBase | null>(null);
    const [notice, setNotice] = useState<Notice | null>(null);

    // Builder form.
    const [scenarioName, setScenarioName] = useState("");
    const [description, setDescription] = useState("");
    const [baseAsOf, setBaseAsOf] = useState<string>(
        new Date().toISOString().slice(0, 10),
    );
    const [horizon, setHorizon] = useState("12");
    const [actions, setActions] = useState<DraftAction[]>([]);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    // Opened scenario + version history + comparison.
    const [lastCreated, setLastCreated] = useState<Scenario | null>(null);
    const [history, setHistory] = useState<ScenarioListItem[]>([]);
    const [historyError, setHistoryError] = useState<string | null>(null);
    const [opened, setOpened] = useState<Scenario | null>(null);
    const [openedLoading, setOpenedLoading] = useState(false);
    const [compare, setCompare] = useState<ScenarioCompareItem[]>([]);
    const [compareIds, setCompareIds] = useState<CompareSelection[]>([]);
    const [compareLoading, setCompareLoading] = useState(false);

    const loadBase = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            setBase(await getPayrollBase());
            setStatus({ state: "ready" });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load the planning base.",
            });
        }
    }, []);

    const loadHistory = useCallback(async () => {
        setHistoryError(null);
        try {
            setHistory(await listScenarios());
        } catch (error) {
            setHistoryError(
                error instanceof ApiError
                    ? error.message
                    : "Could not load saved scenarios.",
            );
        }
    }, []);

    useEffect(() => {
        void loadBase();
        void loadHistory();
    }, [loadBase, loadHistory]);

    useEffect(() => {
        if (compareIds.length < 2) {
            setCompare([]);
            return;
        }
        setCompareLoading(true);
        compareScenarios(compareIds.map((item) => item.id))
            .then(setCompare)
            .catch(() => setCompare([]))
            .finally(() => setCompareLoading(false));
    }, [compareIds]);

    const currency = base?.currency ?? "USD";

    const employeeOptions = useMemo<SearchableSelectOption[]>(
        () =>
            (base?.employees ?? []).map((employee) => ({
                value: employee.employee_id,
                label: `${employee.first_name} ${employee.last_name}`,
                hint: employee.job_title,
                keywords: employee.employee_number,
            })),
        [base],
    );

    const employeeById = useMemo(
        () =>
            new Map(
                (base?.employees ?? []).map((employee) => [
                    employee.employee_id,
                    employee,
                ]),
            ),
        [base],
    );

    const budgetPerMonth = base
        ? Number(base.monthly_salary_total) +
          Number(base.monthly_benefit_cost_total)
        : 0;

    function updateAction(
        key: string,
        patch: Partial<DraftAction>,
    ) {
        setActions((current) =>
            current.map((action) =>
                action.key === key ? { ...action, ...patch } : action,
            ),
        );
    }

    function toCreateActions(): ScenarioAction[] | null {
        const horizonMonths = Number(horizon);
        if (!Number.isInteger(horizonMonths) || horizonMonths < 1) {
            setFormError("Horizon must be a whole number of months (1-36).");
            return null;
        }
        if (horizonMonths > 36) {
            setFormError("Horizon is capped at 36 months.");
            return null;
        }
        const out: ScenarioAction[] = [];
        for (const action of actions) {
            const month = Number(action.effective_month);
            if (!Number.isInteger(month) || month < 1 || month > horizonMonths) {
                setFormError(
                    "Every action's effective month must fall within the horizon.",
                );
                return null;
            }
            if (action.type === "salary_merit") {
                const percent = Number(action.percent);
                if (
                    !Number.isFinite(percent) ||
                    percent <= 0 ||
                    percent > 1
                ) {
                    setFormError(
                        "Salary merit percent must be between 0 and 100% (e.g. 0.05).",
                    );
                    return null;
                }
                out.push({
                    type: "salary_merit",
                    percent: action.percent.trim(),
                    effective_month: month,
                });
            } else if (action.type === "new_hire") {
                if (
                    !action.first_name.trim() ||
                    !action.last_name.trim() ||
                    !action.job_title.trim()
                ) {
                    setFormError("Every new hire needs a name and job title.");
                    return null;
                }
                const salary = Number(action.monthly_salary);
                const benefit = Number(action.monthly_benefit_cost);
                if (!Number.isFinite(salary) || salary <= 0) {
                    setFormError("New hire monthly salary must be positive.");
                    return null;
                }
                if (!Number.isFinite(benefit) || benefit < 0) {
                    setFormError(
                        "New hire monthly benefit cost must be zero or positive.",
                    );
                    return null;
                }
                if (!/^\d{4}-\d{2}-\d{2}$/.test(action.hire_date)) {
                    setFormError("New hire needs a valid hire date.");
                    return null;
                }
                out.push({
                    type: "new_hire",
                    effective_month: month,
                    employee: {
                        first_name: action.first_name.trim(),
                        last_name: action.last_name.trim(),
                        department_id:
                            action.department_id || undefined,
                        department_name: action.department_name || undefined,
                        job_title: action.job_title.trim(),
                        hire_date: action.hire_date,
                        monthly_salary: action.monthly_salary.trim(),
                        currency,
                        monthly_benefit_cost: action.monthly_benefit_cost.trim() || "0.00",
                    },
                });
            } else if (action.type === "reduction") {
                if (!action.employee_id) {
                    setFormError("Pick an employee for the reduction.");
                    return null;
                }
                out.push({
                    type: "reduction",
                    employee_id: action.employee_id,
                    effective_month: month,
                });
            } else {
                if (!action.employee_id) {
                    setFormError("Pick an employee for the benefit change.");
                    return null;
                }
                const benefit = Number(action.monthly_benefit_cost);
                if (!Number.isFinite(benefit) || benefit < 0) {
                    setFormError(
                        "Benefit cost must be zero or positive.",
                    );
                    return null;
                }
                out.push({
                    type: "benefit_change",
                    employee_id: action.employee_id,
                    monthly_benefit_cost:
                        action.monthly_benefit_cost.trim() || "0.00",
                    effective_month: month,
                });
            }
        }
        return out;
    }

    async function onRunProjection(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (saving) return;
        setFormError(null);
        if (!scenarioName.trim()) {
            setFormError("Name the scenario so it can be revisited later.");
            return;
        }
        if (!baseAsOf) {
            setFormError("Choose a base date for the projection.");
            return;
        }
        const createActions = toCreateActions();
        if (!createActions) return;
        setSaving(true);
        try {
            const scenario = await createScenario({
                name: scenarioName.trim(),
                description: description.trim() || undefined,
                base_as_of: baseAsOf,
                horizon: Number(horizon),
                actions: createActions,
            });
            setLastCreated(scenario);
            setNotice({
                tone: "success",
                text: `Scenario "${scenario.name}" saved (${formatDate(scenario.base_as_of)}).`,
            });
            await loadHistory();
        } catch (error) {
            setNotice({
                tone: "error",
                text:
                    error instanceof ApiError
                        ? error.message
                        : "Could not run the projection.",
            });
        } finally {
            setSaving(false);
        }
    }

    async function openScenario(id: string) {
        setOpenedLoading(true);
        setOpened(null);
        try {
            setOpened(await getScenario(id));
        } catch (error) {
            setNotice({
                tone: "error",
                text:
                    error instanceof ApiError
                        ? error.message
                        : "Could not open the scenario.",
            });
        } finally {
            setOpenedLoading(false);
        }
    }

    function toggleCompare(item: ScenarioListItem) {
        setCompareIds((current) => {
            const present = current.some((entry) => entry.id === item.id);
            if (present) {
                return current.filter((entry) => entry.id !== item.id);
            }
            if (current.length >= 3) {
                setNotice({
                    tone: "error",
                    text: "Compare is limited to 3 scenarios.",
                });
                return current;
            }
            return [...current, { id: item.id, name: item.name }];
        });
    }

const openSeries = useMemo(
        () =>
            lastCreated?.projection
                ? [lastCreated]
                : opened
                  ? [opened]
                  : [],
        [lastCreated, opened],
    );

    const featuredProjection = lastCreated?.projection ?? opened?.projection ?? null;

    return (
        <div className="space-y-6">
            <PageHeader
                title="Planning studio"
                description="Model workforce cost what-ifs on the live payroll base and freeze them as revisitable scenarios."
                icon={SlidersHorizontal}
            />

            {notice ? (
                <div
                    role={notice.tone === "error" ? "alert" : "status"}
                    className={cn(
                        "rounded-lg border px-3 py-2 text-sm font-medium",
                        notice.tone === "error"
                            ? "border-destructive/40 bg-destructive/5 text-destructive"
                            : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                    )}
                >
                    {notice.text}
                </div>
            ) : null}

            {status.state === "loading" ? (
                <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
                    <LoaderCircle
                        aria-hidden="true"
                        className="size-4 animate-spin"
                    />
                    Loading planning base…
                </div>
            ) : null}

            {status.state === "error" ? (
                <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
                    <p className="text-sm font-medium text-destructive">
                        {status.message}
                    </p>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => void loadBase()}
                    >
                        Try again
                    </Button>
                </div>
            ) : null}

            {status.state === "ready" && base ? (
                <>
                    <section className="rounded-xl border border-border bg-card p-5">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                                    Scenario builder
                                </h2>
                                <p className="mt-0.5 text-sm text-muted-foreground">
                                    Project {base.headcount} employees from their
                                    current base ({formatDate(base.as_of)}).
                                </p>
                            </div>
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                <Badge variant="outline">
                                    {formatMoney(
                                        base.monthly_salary_total,
                                        currency,
                                    )}{" "}
                                    salary / mo
                                </Badge>
                                <Badge variant="outline">
                                    {formatMoney(
                                        base.monthly_benefit_cost_total,
                                        currency,
                                    )}{" "}
                                    benefits / mo
                                </Badge>
                            </div>
                        </div>

                        <form
                            className="mt-5 space-y-5"
                            onSubmit={(event) => void onRunProjection(event)}
                        >
                            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                                <div className="space-y-1.5">
                                    <Label htmlFor="scenario-name">
                                        Scenario name
                                    </Label>
                                    <Input
                                        id="scenario-name"
                                        value={scenarioName}
                                        onChange={(event) =>
                                            setScenarioName(event.target.value)
                                        }
                                        placeholder="e.g. Reset team top-ups"
                                        maxLength={120}
                                        required
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="scenario-description">
                                        Description
                                    </Label>
                                    <Input
                                        id="scenario-description"
                                        value={description}
                                        onChange={(event) =>
                                            setDescription(event.target.value)
                                        }
                                        placeholder="Optional note on intent"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="scenario-base">
                                        Base date
                                    </Label>
                                    <DatePicker
                                        id="scenario-base"
                                        value={baseAsOf}
                                        onChange={(iso) =>
                                            setBaseAsOf(iso ?? "")
                                        }
                                        required
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <Label htmlFor="scenario-horizon">
                                        Horizon (months)
                                    </Label>
                                    <Input
                                        id="scenario-horizon"
                                        inputMode="numeric"
                                        value={horizon}
                                        onChange={(event) =>
                                            setHorizon(event.target.value)
                                        }
                                        required
                                    />
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <h3 className="font-display text-sm font-semibold tracking-tight text-foreground">
                                        Actions
                                    </h3>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() =>
                                            setActions((current) => [
                                                ...current,
                                                emptyDraftAction(),
                                            ])
                                        }
                                    >
                                        <Plus
                                            aria-hidden="true"
                                            className="size-4"
                                        />
                                        Add action
                                    </Button>
                                </div>

                                {actions.length === 0 ? (
                                    <p className="text-sm text-muted-foreground">
                                        No actions yet — this scenario projects
                                        the payroll base unchanged. Add a merit
                                        increase, new hire, reduction, or
                                        benefit change to model a what-if.
                                    </p>
                                ) : (
                                    <div className="space-y-3">
                                        {actions.map((action, index) => (
                                            <ActionRow
                                                key={action.key}
                                                action={action}
                                                index={index}
                                                currency={currency}
                                                employees={employeeOptions}
                                                employee={
                                                    employeeById.get(
                                                        action.employee_id,
                                                    ) ?? null
                                                }
                                                onChange={updateAction}
                                                onRemove={() =>
                                                    setActions((current) =>
                                                        current.filter(
                                                            (entry) =>
                                                                entry.key !==
                                                                action.key,
                                                        ),
                                                    )
                                                }
                                            />
                                        ))}
                                    </div>
                                )}
                            </div>

                            {formError ? (
                                <p
                                    role="alert"
                                    className="text-sm font-medium text-destructive"
                                >
                                    {formError}
                                </p>
                            ) : null}

                            <div className="flex flex-wrap items-center gap-3">
                                <Button type="submit" disabled={saving || !base}>
                                    {saving ? (
                                        <LoaderCircle
                                            aria-hidden="true"
                                            className="size-4 animate-spin"
                                        />
                                    ) : (
                                        <TrendingUp
                                            aria-hidden="true"
                                            className="size-4"
                                        />
                                    )}
                                    {saving ? "Projecting…" : "Run projection"}
                                </Button>
                                <p className="text-xs text-muted-foreground">
                                    Scenarios are frozen on save — each run is
                                    a separate version in history.
                                </p>
                            </div>
                        </form>
                    </section>

                    {featuredProjection ? (
                        <section className="rounded-xl border border-border bg-card p-5">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                                <div>
                                    <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                                        Projection —{" "}
                                        {lastCreated?.name ?? opened?.name}
                                    </h2>
                                    <p className="mt-0.5 text-sm text-muted-foreground">
                                        Salary and benefits run-rate vs. the
                                        unchanged base budget.
                                    </p>
                                </div>
                                <div className="flex items-center gap-2 text-sm">
                                    <Badge variant="secondary">
                                        Salary{" "}
                                        {formatMoney(
                                            featuredProjection.salary_total,
                                            featuredProjection.currency,
                                        )}
                                    </Badge>
                                    <Badge variant="secondary">
                                        Benefits{" "}
                                        {formatMoney(
                                            featuredProjection.benefit_total,
                                            featuredProjection.currency,
                                        )}
                                    </Badge>
                                    <Badge>
                                        Total{" "}
                                        {formatMoney(
                                            featuredProjection.grand_total,
                                            featuredProjection.currency,
                                        )}
                                    </Badge>
                                </div>
                            </div>
                            <ProjectionChart
                                projections={openSeries.map((scenario) => ({
                                    name: scenario.name,
                                    projection: scenario.projection,
                                }))}
                                compare={compare}
                                currency={currency}
                                budgetPerMonth={budgetPerMonth}
                            />
                        </section>
                    ) : null}

                    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                        <section className="rounded-xl border border-border bg-card p-5">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                                        Compare (up to 3)
                                    </h2>
                                    <p className="mt-0.5 text-sm text-muted-foreground">
                                        Pick saved scenarios to plot their cost
                                        lines against each other.
                                    </p>
                                </div>
                                {compareLoading ? (
                                    <LoaderCircle
                                        aria-hidden="true"
                                        className="size-4 animate-spin text-muted-foreground"
                                    />
                                ) : null}
                            </div>
                            <div className="mt-4 space-y-2">
                                {history.length === 0 ? (
                                    <p className="text-sm text-muted-foreground">
                                        No scenarios saved yet.
                                    </p>
                                ) : (
                                    history.map((item) => {
                                        const selected = compareIds.some(
                                            (entry) => entry.id === item.id,
                                        );
                                        return (
                                            <button
                                                key={item.id}
                                                type="button"
                                                onClick={() =>
                                                    toggleCompare(item)
                                                }
                                                className={cn(
                                                    "flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                                                    selected
                                                        ? "border-primary/50 bg-primary/5"
                                                        : "border-border hover:bg-muted/60",
                                                )}
                                            >
                                                <span className="min-w-0 truncate font-medium">
                                                    {item.name}
                                                </span>
                                                <Badge
                                                    variant={
                                                        selected
                                                            ? "default"
                                                            : "outline"
                                                    }
                                                >
                                                    {item.horizon} mo
                                                </Badge>
                                            </button>
                                        );
                                    })
                                )}
                            </div>
                            {compare.length > 0 ? (
                                <ComparisonTable
                                    compare={compare}
                                    currency={currency}
                                />
                            ) : null}
                        </section>

                        <section className="rounded-xl border border-border bg-card p-5">
                            <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                                Version history
                            </h2>
                            <p className="mt-0.5 text-sm text-muted-foreground">
                                Every run is frozen and kept as a version.
                            </p>
                            <div className="mt-4 space-y-2">
                                {historyError ? (
                                    <p className="text-sm font-medium text-destructive">
                                        {historyError}
                                    </p>
                                ) : history.length === 0 ? (
                                    <p className="text-sm text-muted-foreground">
                                        No versions saved yet.
                                    </p>
                                ) : (
                                    history.map((item) => (
                                        <button
                                            key={item.id}
                                            type="button"
                                            onClick={() =>
                                                void openScenario(item.id)
                                            }
                                            disabled={openedLoading}
                                            className={cn(
                                                "flex w-full items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-left text-sm transition-colors",
                                                "hover:bg-muted/60 disabled:opacity-60",
                                            )}
                                        >
                                            <span className="min-w-0">
                                                <span className="block truncate font-medium">
                                                    {item.name}
                                                </span>
                                                <span className="block text-xs text-muted-foreground">
                                                    {formatDate(item.created_at)}
                                                </span>
                                            </span>
                                            <Badge variant="outline">
                                                {item.horizon} mo
                                            </Badge>
                                        </button>
                                    ))
                                )}
                            </div>
                        </section>
                    </div>
                </>
            ) : null}
        </div>
    );
}

function ActionRow({
    action,
    index,
    currency,
    employees,
    employee,
    onChange,
    onRemove,
}: {
    action: DraftAction;
    index: number;
    currency: string;
    employees: SearchableSelectOption[];
    employee: PayrollBase["employees"][number] | null;
    onChange: (key: string, patch: Partial<DraftAction>) => void;
    onRemove: () => void;
}) {
    const change = (patch: Partial<DraftAction>) => onChange(action.key, patch);
    const selectedHire = Boolean(action.department_id);
    return (
        <div className="rounded-lg border border-border bg-muted/20 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-medium text-muted-foreground">
                        Action {index + 1}
                    </span>
                    {ACTION_TYPES.map((type) => (
                        <button
                            key={type.value}
                            type="button"
                            onClick={() => change({ type: type.value })}
                            className={cn(
                                "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
                                action.type === type.value
                                    ? "border-primary bg-primary/10 text-primary"
                                    : "border-border text-muted-foreground hover:bg-muted",
                            )}
                        >
                            {type.label}
                        </button>
                    ))}
                </div>
                <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label="Remove action"
                    onClick={onRemove}
                >
                    <Trash2 aria-hidden="true" className="size-4" />
                </Button>
            </div>

            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {action.type === "salary_merit" ? (
                    <>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-percent`}>
                                Merit percent
                            </Label>
                            <Input
                                id={`action-${action.key}-percent`}
                                inputMode="decimal"
                                placeholder="0.05 = 5%"
                                value={action.percent}
                                onChange={(event) =>
                                    change({ percent: event.target.value })
                                }
                            />
                        </div>
                        <MonthInput
                            id={`action-${action.key}-month`}
                            label="Effective month"
                            value={action.effective_month}
                            onChange={(value) =>
                                change({ effective_month: value })
                            }
                        />
                    </>
                ) : null}

                {action.type === "new_hire" ? (
                    <>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-first`}>
                                First name
                            </Label>
                            <Input
                                id={`action-${action.key}-first`}
                                value={action.first_name}
                                onChange={(event) =>
                                    change({ first_name: event.target.value })
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-last`}>
                                Last name
                            </Label>
                            <Input
                                id={`action-${action.key}-last`}
                                value={action.last_name}
                                onChange={(event) =>
                                    change({ last_name: event.target.value })
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-title`}>
                                Job title
                            </Label>
                            <Input
                                id={`action-${action.key}-title`}
                                value={action.job_title}
                                onChange={(event) =>
                                    change({ job_title: event.target.value })
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-hire`}>
                                Hire date
                            </Label>
                            <DatePicker
                                id={`action-${action.key}-hire`}
                                value={action.hire_date}
                                onChange={(iso) =>
                                    change({ hire_date: iso ?? "" })
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-salary`}>
                                Monthly salary ({currency})
                            </Label>
                            <Input
                                id={`action-${action.key}-salary`}
                                inputMode="decimal"
                                value={action.monthly_salary}
                                onChange={(event) =>
                                    change({ monthly_salary: event.target.value })
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-benefit`}>
                                Monthly benefit cost ({currency})
                            </Label>
                            <Input
                                id={`action-${action.key}-benefit`}
                                inputMode="decimal"
                                value={action.monthly_benefit_cost}
                                onChange={(event) =>
                                    change({
                                        monthly_benefit_cost: event.target.value,
                                    })
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label>Department (optional)</Label>
                            <SearchableSelect
                                options={employees}
                                value={action.department_id || null}
                                onValueChange={(value) => {
                                    change({
                                        department_id: value,
                                        department_name:
                                            employees.find(
                                                (option) =>
                                                    option.value === value,
                                            )?.label ?? "",
                                    });
                                }}
                                placeholder={
                                    selectedHire
                                        ? "Clear to leave unassigned"
                                        : "Choose a department"
                                }
                            />
                        </div>
                        <MonthInput
                            id={`action-${action.key}-month`}
                            label="Effective month"
                            value={action.effective_month}
                            onChange={(value) =>
                                change({ effective_month: value })
                            }
                        />
                    </>
                ) : null}

                {action.type === "reduction" ? (
                    <>
                        <div className="space-y-1.5 sm:col-span-2">
                            <Label htmlFor={`action-${action.key}-employee`}>
                                Employee
                            </Label>
                            <SearchableSelect
                                id={`action-${action.key}-employee`}
                                options={employees}
                                value={action.employee_id || null}
                                onValueChange={(value) =>
                                    change({ employee_id: value })
                                }
                                placeholder="Choose an employee"
                            />
                        </div>
                        <MonthInput
                            id={`action-${action.key}-month`}
                            label="Effective month"
                            value={action.effective_month}
                            onChange={(value) =>
                                change({ effective_month: value })
                            }
                        />
                    </>
                ) : null}

                {action.type === "benefit_change" ? (
                    <>
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-employee`}>
                                Employee
                            </Label>
                            <SearchableSelect
                                id={`action-${action.key}-employee`}
                                options={employees}
                                value={action.employee_id || null}
                                onValueChange={(value) =>
                                    change({ employee_id: value })
                                }
                                placeholder="Choose an employee"
                            />
                        </div>
                        {employee ? (
                            <div className="flex items-end pb-1.5">
                                <Badge variant="outline">
                                    Currently{" "}
                                    {formatMoney(
                                        employee.monthly_benefit_cost,
                                        employee.currency,
                                    )}{" "}
                                    / mo
                                </Badge>
                            </div>
                        ) : null}
                        <div className="space-y-1.5">
                            <Label htmlFor={`action-${action.key}-benefit`}>
                                New monthly benefit cost ({currency})
                            </Label>
                            <Input
                                id={`action-${action.key}-benefit`}
                                inputMode="decimal"
                                value={action.monthly_benefit_cost}
                                onChange={(event) =>
                                    change({
                                        monthly_benefit_cost: event.target.value,
                                    })
                                }
                            />
                        </div>
                        <MonthInput
                            id={`action-${action.key}-month`}
                            label="Effective month"
                            value={action.effective_month}
                            onChange={(value) =>
                                change({ effective_month: value })
                            }
                        />
                    </>
                ) : null}
            </div>
        </div>
    );
}

function MonthInput({
    id,
    label,
    value,
    onChange,
}: {
    id: string;
    label: string;
    value: string;
    onChange: (value: string) => void;
}) {
    return (
        <div className="space-y-1.5">
            <Label htmlFor={id}>{label}</Label>
            <Input
                id={id}
                inputMode="numeric"
                value={value}
                onChange={(event) => onChange(event.target.value)}
            />
        </div>
    );
}

function ProjectionChart({
    projections,
    compare,
    currency,
    budgetPerMonth,
}: {
    projections: Array<{ name: string; projection: Projection }>;
    compare: ScenarioCompareItem[];
    currency: string;
    budgetPerMonth: number;
}) {
    const series = compare.length > 0 ? compare : projections;
    if (series.length === 0) return null;

    const data: Array<Record<string, number | string>> = [];
    const count = series[0].projection.horizon;
    for (let monthIndex = 0; monthIndex < count; monthIndex += 1) {
        const row: Record<string, number | string> = {
            month: `M${monthIndex + 1}`,
            budget: budgetPerMonth,
        };
        series.forEach((item) => {
            const month = item.projection.months[monthIndex];
            row[item.name] = month ? Number(month.total_cost) : 0;
        });
        data.push(row);
    }

    return (
        <div className="mt-4 h-72">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart
                    data={data}
                    margin={{
                        top: 4,
                        right: 8,
                        left: 0,
                        bottom: 0,
                    }}
                >
                    <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="var(--border)"
                    />
                    <XAxis
                        dataKey="month"
                        tick={axisTick}
                        stroke="var(--border)"
                    />
                    <YAxis
                        tick={axisTick}
                        stroke="var(--border)"
                        tickFormatter={(value: number) =>
                            compactMoneyFormatter.format(value)
                        }
                    />
                    <Tooltip
                        content={<ChartTooltip currency={currency} />}
                    />
                    <Legend wrapperStyle={{ fontSize: "12px" }} />
                    <ReferenceLine
                        y={budgetPerMonth}
                        stroke={BUDGET_COLOR}
                        strokeDasharray="6 3"
                        label={{
                            value: "Base budget",
                            position: "insideBottomRight",
                            fill: BUDGET_COLOR,
                            fontSize: 11,
                        }}
                    />
                    {series.map((item, index) => (
                        <Line
                            key={item.name}
                            type="monotone"
                            dataKey={item.name}
                            stroke={
                                SERIES_COLORS[index % SERIES_COLORS.length]
                            }
                            strokeWidth={2}
                            dot={false}
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}

function ChartTooltip({
    active,
    payload,
    label,
    currency,
}: {
    active?: boolean;
    payload?: ReadonlyArray<{
        name?: string | number;
        value?: number | [number, number] | string;
        color?: string;
    }>;
    label?: string | number;
    currency: string;
}) {
    if (!active || !payload || payload.length === 0) return null;
    return (
        <div className="rounded-lg border border-border bg-popover px-3 py-2 text-sm shadow-md">
            <p className="mb-1 font-medium text-foreground">
                Month {label} · per-month run-rate
            </p>
            <ul className="space-y-1">
                {payload.map((entry, index) => {
                    const amount = Array.isArray(entry.value)
                        ? entry.value[0]
                        : entry.value;
                    return (
                        <li
                            key={index}
                            className="flex items-center gap-2 text-muted-foreground"
                        >
                            <span
                                aria-hidden="true"
                                className="size-2 shrink-0 rounded-full"
                                style={{
                                    backgroundColor:
                                        entry.color ?? "var(--chart-1)",
                                }}
                            />
                            <span className="min-w-0 flex-1 truncate">
                                {entry.name === "budget"
                                    ? "Base budget"
                                    : String(entry.name)}
                            </span>
                            <span className="tabular-nums text-foreground">
                                {formatMoney(
                                    String(amount ?? 0),
                                    currency,
                                )}
                            </span>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

function ComparisonTable({
    compare,
    currency,
}: {
    compare: ScenarioCompareItem[];
    currency: string;
}) {
    const months = compare[0]?.projection.horizon ?? 0;
    return (
        <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-96 text-left text-sm">
                <thead>
                    <tr className="border-b border-border text-xs text-muted-foreground">
                        <th className="py-2 pr-3 font-medium">Metric</th>
                        {compare.map((item) => (
                            <th
                                key={item.id}
                                className="py-2 pr-3 font-medium"
                            >
                                {item.name}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody className="text-muted-foreground">
                    <tr className="border-b border-border/60">
                        <td className="py-2 pr-3">Base date</td>
                        {compare.map((item) => (
                            <td
                                key={item.id}
                                className="py-2 pr-3 tabular-nums"
                            >
                                {formatDate(item.base_as_of)}
                            </td>
                        ))}
                    </tr>
                    <tr className="border-b border-border/60">
                        <td className="py-2 pr-3">Horizon</td>
                        {compare.map((item) => (
                            <td
                                key={item.id}
                                className="py-2 pr-3 tabular-nums"
                            >
                                {item.horizon} months
                            </td>
                        ))}
                    </tr>
                    <tr className="border-b border-border/60">
                        <td className="py-2 pr-3">Salary total</td>
                        {compare.map((item) => (
                            <td
                                key={item.id}
                                className="py-2 pr-3 tabular-nums text-foreground"
                            >
                                {formatMoney(
                                    item.projection.salary_total,
                                    currency,
                                )}
                            </td>
                        ))}
                    </tr>
                    <tr className="border-b border-border/60">
                        <td className="py-2 pr-3">Benefit total</td>
                        {compare.map((item) => (
                            <td
                                key={item.id}
                                className="py-2 pr-3 tabular-nums text-foreground"
                            >
                                {formatMoney(
                                    item.projection.benefit_total,
                                    currency,
                                )}
                            </td>
                        ))}
                    </tr>
                    <tr>
                        <td className="py-2 pr-3 font-medium text-foreground">
                            Grand total
                        </td>
                        {compare.map((item) => (
                            <td
                                key={item.id}
                                className="py-2 pr-3 tabular-nums font-medium text-foreground"
                            >
                                {formatMoney(
                                    item.projection.grand_total,
                                    currency,
                                )}
                            </td>
                        ))}
                    </tr>
                </tbody>
            </table>
            {months > 0 ? (
                <div className="mt-3 space-y-1">
                    <p className="text-xs text-muted-foreground">
                        Peak headcount per scenario
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {compare.map((item) => {
                            const peak = item.projection.months.reduce(
                                (max, month) =>
                                    Math.max(max, month.headcount),
                                0,
                            );
                            return (
                                <Badge key={item.id} variant="outline">
                                    {item.name}: {peak}
                                </Badge>
                            );
                        })}
                    </div>
                </div>
            ) : null}
        </div>
    );
}