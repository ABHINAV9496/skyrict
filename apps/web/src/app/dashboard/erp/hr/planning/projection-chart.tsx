"use client";

import { useMemo } from "react";
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

import { type Projection, type ScenarioCompareItem } from "@/lib/api/hr-planning-api";
import { formatMoney } from "@/lib/format";

// Hoisted to module scope: recharts re-renders on every new inline object /
// callback reference, so these must stay stable across renders.
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

export function PlanningProjectionChart({
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
    const tooltipContent = useMemo(
        () => <ChartTooltip currency={currency} />,
        [currency],
    );

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
                    margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
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
                    <Tooltip content={tooltipContent} />
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
                            stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                            strokeWidth={2}
                            dot={false}
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}