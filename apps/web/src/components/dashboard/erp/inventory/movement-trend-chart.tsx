"use client";

import {
    Bar,
    BarChart,
    CartesianGrid,
    Legend,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

// Hoisted to module scope: recharts re-renders on every new inline object /
// callback reference, so these must stay stable across renders.
const AXIS_TICK = { fontSize: 12 } as const;
const GRID_STROKE = { strokeDasharray: "3 3", stroke: "var(--border)" } as const;
const SERIES = [
    { dataKey: "Receipts", stackId: "movement", fill: "var(--primary)" },
    { dataKey: "Issues", stackId: "movement", fill: "#f59e0b" },
    { dataKey: "Adjustments", stackId: "movement", fill: "#8b5cf6" },
] as const;

export interface MovementTrendPoint {
    week: string;
    Receipts: number;
    Issues: number;
    Adjustments: number;
}

export function MovementTrendChart({ data }: { data: MovementTrendPoint[] }) {
    return (
        <div className="h-72 rounded-xl border border-border bg-card p-4">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data}>
                    <CartesianGrid {...GRID_STROKE} />
                    <XAxis dataKey="week" tick={AXIS_TICK} stroke="var(--muted-foreground)" />
                    <YAxis
                        tick={AXIS_TICK}
                        stroke="var(--muted-foreground)"
                        allowDecimals={false}
                    />
                    <Tooltip />
                    <Legend />
                    {SERIES.map((series) => (
                        <Bar key={series.dataKey} {...series} />
                    ))}
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}