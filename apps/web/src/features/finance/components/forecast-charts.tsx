"use client";

import {
    Area,
    Bar,
    BarChart,
    CartesianGrid,
    ComposedChart,
    Line,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import { formatMoney } from "@/lib/finance/format";

// Hoisted to module scope: recharts re-renders on every new inline object /
// callback reference, so these must stay stable across renders. Series colors
// are passed in from the owning card as primitives (stable identity).
const axisTick = {
    fontSize: 11,
    fill: "var(--muted-foreground)",
    fontFamily: "var(--font-sans)",
};
const compactMoneyFormatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
});
const GRID = { stroke: "var(--border)", strokeOpacity: 0.6, vertical: false } as const;

function compactMoney(value: number): string {
    return compactMoneyFormatter.format(value);
}

export interface ForecastPoint {
    label: string;
    predicted: number;
    baseline?: number | null;
    pipeline?: number | null;
    band: [number, number] | null;
}

export interface HistoryPoint {
    label: string;
    actual: number;
}

function ChartTooltipContent({
    active,
    payload,
    label,
}: {
    active: boolean;
    payload?: ReadonlyArray<{
        name?: string;
        value?: number | [number, number];
        color?: string;
        payload?: { baseline?: number | null; pipeline?: number | null };
    }>;
    label?: string;
}) {
    if (!active || !payload || payload.length === 0) return null;
    const datum = payload[0]?.payload;
    const hasBreakdown = datum?.baseline != null && datum?.pipeline != null;
    const predictedEntry = payload.find((entry) => entry.name === "Forecast");
    return (
        <div className="rounded-lg border border-border bg-popover px-3 py-2 shadow-md">
            {label ? (
                <p className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                    {label}
                </p>
            ) : null}
            <ul className="space-y-1">
                {payload.map((entry, index) => (
                    <li key={index} className="flex items-center gap-2 text-sm">
                        <span
                            aria-hidden="true"
                            className="size-2 shrink-0 rounded-full"
                            style={{
                                backgroundColor:
                                    entry.color ?? "var(--chart-1)",
                            }}
                        />
                        <span className="text-muted-foreground">
                            {entry.name}
                        </span>
                        <span className="ml-auto pl-3 font-semibold tabular-nums text-foreground">
                            {Array.isArray(entry.value)
                                ? `${formatMoney(entry.value[0])} - ${formatMoney(entry.value[1])}`
                                : formatMoney(entry.value ?? 0)}
                        </span>
                    </li>
                ))}
            </ul>
            {hasBreakdown ? (
                <p className="mt-2 border-t border-border/60 pt-1.5 text-xs tabular-nums text-muted-foreground">
                    {formatMoney(datum!.baseline!)} usual revenue
                    {datum!.pipeline! > 0 ? (
                        <> + {formatMoney(datum!.pipeline!)} deals closing</>
                    ) : null}{" "}
                    = {formatMoney((predictedEntry?.value as number) ?? 0)}
                </p>
            ) : null}
        </div>
    );
}

export function RevenueForecastChart({
    data,
    hasDecomposition,
    predictedColor,
    bandColor,
    baselineColor,
}: {
    data: ForecastPoint[];
    hasDecomposition: boolean;
    predictedColor: string;
    bandColor: string;
    baselineColor: string;
}) {
    return (
        <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                    data={data}
                    margin={{ top: 4, right: 4, left: 0, bottom: 0 }}
                >
                    <defs>
                        <linearGradient
                            id="forecastBand"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                        >
                            <stop
                                offset="0%"
                                stopColor={bandColor}
                                stopOpacity={0.24}
                            />
                            <stop
                                offset="100%"
                                stopColor={bandColor}
                                stopOpacity={0.04}
                            />
                        </linearGradient>
                    </defs>
                    <CartesianGrid {...GRID} />
                    <XAxis
                        dataKey="label"
                        tick={axisTick}
                        axisLine={false}
                        tickLine={false}
                        tickMargin={8}
                        interval="preserveStartEnd"
                    />
                    <YAxis
                        tick={axisTick}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={compactMoney}
                        domain={[0, "auto"]}
                        width={52}
                    />
                    <Tooltip
                        cursor={{
                            stroke: "var(--border)",
                            strokeOpacity: 0.9,
                        }}
                        content={({ active, payload, label }) => (
                            <ChartTooltipContent
                                active={Boolean(active)}
                                payload={
                                    payload as ReadonlyArray<{
                                        name?: string;
                                        value?: number | [number, number];
                                        color?: string;
                                    }>
                                }
                                label={label as string | undefined}
                            />
                        )}
                    />
                    <Area
                        dataKey="band"
                        name="Expected range"
                        stroke="none"
                        fill="url(#forecastBand)"
                        activeDot={false}
                        legendType="none"
                    />
                    <Line
                        type="monotone"
                        dataKey="predicted"
                        name="Forecast"
                        stroke={predictedColor}
                        strokeWidth={2.5}
                        dot={false}
                        activeDot={{
                            r: 4,
                            strokeWidth: 2,
                            stroke: "var(--card)",
                        }}
                        legendType="none"
                    />
                    {hasDecomposition ? (
                        <Line
                            type="monotone"
                            dataKey="baseline"
                            name="Usual revenue"
                            stroke={baselineColor}
                            strokeWidth={1.5}
                            strokeDasharray="4 4"
                            dot={false}
                            activeDot={false}
                            legendType="none"
                        />
                    ) : null}
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}

export function RevenueHistoryChart({
    data,
    actualColor,
}: {
    data: HistoryPoint[];
    actualColor: string;
}) {
    return (
        <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart
                    data={data}
                    margin={{ top: 4, right: 4, left: 0, bottom: 0 }}
                >
                    <CartesianGrid {...GRID} />
                    <XAxis
                        dataKey="label"
                        tick={axisTick}
                        axisLine={false}
                        tickLine={false}
                        tickMargin={8}
                        interval="preserveStartEnd"
                    />
                    <YAxis
                        tick={axisTick}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={compactMoney}
                        domain={[0, "auto"]}
                        width={52}
                    />
                    <Tooltip
                        cursor={{ fill: "var(--card)", fillOpacity: 0.55 }}
                        content={({ active, payload, label }) => (
                            <ChartTooltipContent
                                active={Boolean(active)}
                                payload={
                                    payload as ReadonlyArray<{
                                        name?: string;
                                        value?: number | [number, number];
                                        color?: string;
                                    }>
                                }
                                label={label as string | undefined}
                            />
                        )}
                    />
                    <Bar
                        dataKey="actual"
                        name="Actual"
                        fill={actualColor}
                        fillOpacity={0.9}
                        radius={[4, 4, 0, 0]}
                        maxBarSize={36}
                    />
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}