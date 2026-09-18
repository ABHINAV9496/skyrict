"use client";

import { useCallback } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";

import { formatMoney } from "@/lib/format";

// Hoisted to module scope (memoised only where props must flow in): recharts
// re-renders on every new inline object / callback reference.
const AXIS_TICK = { fontSize: 12 } as const;
const MARGIN = { top: 4, right: 8, left: 0, bottom: 0 } as const;
const CURSOR = { fill: "var(--muted)" } as const;

export interface CostTrendPoint {
    key: string;
    label: string;
    amount: number;
}

export function PayrollCostTrendChart({
    data,
    currency,
}: {
    data: CostTrendPoint[];
    currency: string;
}) {
    const tooltipFormatter = useCallback(
        (value: number | string) => formatMoney(Number(value), currency),
        [currency],
    );
    return (
        <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={MARGIN}>
                    <XAxis
                        dataKey="label"
                        tick={AXIS_TICK}
                        stroke="var(--muted-foreground)"
                        interval="preserveStartEnd"
                    />
                    <Tooltip cursor={CURSOR} formatter={tooltipFormatter as never} />
                    <Bar
                        dataKey="amount"
                        fill="var(--primary)"
                        radius={[4, 4, 0, 0]}
                    />
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}