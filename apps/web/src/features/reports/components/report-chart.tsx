"use client";

import { useMemo } from "react";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartPlan } from "@/lib/reports/chartability";
import { formatNumber } from "@/lib/erp/money";

const SERIES_COLORS = ["var(--primary)", "#38bdf8", "#f59e0b", "#a78bfa", "#34d399"];

// Hoisted to module scope: recharts re-renders on every new inline object /
// callback reference, so these must stay stable across renders.
const AXIS_TICK = { fontSize: 12 } as const;
const GRID = { strokeDasharray: "3 3", stroke: "var(--border)" } as const;
const CHART_MARGIN = { top: 4, right: 8, left: 0, bottom: 0 } as const;
const axisTickFormatter = (value: number) => formatNumber(value);
const tooltipFormatter = (value: number | string) => formatNumber(Number(value));

export interface ChartPoint {
  [key: string]: string | number;
}

export function buildChartData(
  plan: ChartPlan,
  rows: Record<string, string>[],
): ChartPoint[] {
  return rows
    .map((row) => {
      const point: ChartPoint = {
        [plan.category]: row[plan.category] ?? "",
      };
      for (const value of plan.values) {
        const parsed = Number(row[value]);
        if (!Number.isFinite(parsed)) return null;
        point[value] = parsed;
      }
      return point;
    })
    .filter((point): point is ChartPoint => point !== null);
}

interface ReportChartProps {
  plan: ChartPlan;
  rows: Record<string, string>[];
}

export function ReportChart({ plan, rows }: ReportChartProps) {
  const data = useMemo(() => buildChartData(plan, rows), [plan, rows]);

  const axes = (
    <>
      <CartesianGrid {...GRID} />
      <XAxis
        dataKey={plan.category}
        tick={AXIS_TICK}
        stroke="var(--muted-foreground)"
      />
      <YAxis
        tick={AXIS_TICK}
        stroke="var(--muted-foreground)"
        tickFormatter={axisTickFormatter}
      />
      <Tooltip formatter={tooltipFormatter as never} />
      <Legend />
    </>
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h2 className="font-display text-sm font-semibold text-foreground">Chart</h2>
      <div className="mt-4 h-72">
        <ResponsiveContainer width="100%" height="100%">
          {plan.kind === "line" ? (
            <LineChart data={data} margin={CHART_MARGIN}>
              {axes}
              {plan.values.map((value, index) => (
                <Line
                  key={value}
                  type="monotone"
                  dataKey={value}
                  stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data} margin={CHART_MARGIN}>
              {axes}
              {plan.values.map((value, index) => (
                <Bar
                  key={value}
                  dataKey={value}
                  fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}