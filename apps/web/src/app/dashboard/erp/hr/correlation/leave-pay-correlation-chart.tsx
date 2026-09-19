"use client";

import {
    CartesianGrid,
    ResponsiveContainer,
    Scatter,
    ScatterChart,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import { formatMoney } from "@/lib/format";

// Hoisted to module scope: recharts re-renders on every new inline object /
// callback reference, so these must stay stable across renders.
const AXIS_TICK = { fontSize: 12 } as const;
const GRID = { strokeDasharray: "3 3", stroke: "var(--border)" } as const;
const MARGIN = { top: 4, right: 8, left: 0, bottom: 0 } as const;
const CURSOR = { strokeDasharray: "3 3" } as const;

const tooltipFormatter = (value: number | string, name: string) =>
    name === "Overtime paid" ? formatMoney(Number(value)) : value;

export interface CorrelationPoint {
    name: string;
    leaveDays: number;
    overtime: number;
}

export function LeavePayCorrelationChart({
    points,
}: {
    points: CorrelationPoint[];
}) {
    return (
        <div className="mt-4 h-72">
            <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={MARGIN}>
                    <CartesianGrid {...GRID} />
                    <XAxis
                        dataKey="leaveDays"
                        name="Leave days"
                        tick={AXIS_TICK}
                        stroke="var(--muted-foreground)"
                    />
                    <YAxis
                        dataKey="overtime"
                        name="Overtime paid"
                        tick={AXIS_TICK}
                        stroke="var(--muted-foreground)"
                    />
                    <Tooltip cursor={CURSOR} formatter={tooltipFormatter as never} />
                    <Scatter data={points} fill="var(--primary)" />
                </ScatterChart>
            </ResponsiveContainer>
        </div>
    );
}