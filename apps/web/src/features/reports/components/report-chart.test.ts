import { createElement, type ComponentType, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportChart, buildChartData } from "@/features/reports/components/report-chart";
import type { ChartPlan } from "@/lib/reports/chartability";

/* ---------- buildChartData (pure, no recharts) ---------- */

describe("buildChartData", () => {
    const plan: ChartPlan = {
        kind: "line",
        category: "month",
        values: ["revenue", "cost"],
    };

    it("parses numeric value columns and keeps the category label", () => {
        const rows = [
            { month: "Jan", revenue: "10", cost: "4" },
            { month: "Feb", revenue: "22", cost: "9" },
        ];
        expect(buildChartData(plan, rows)).toEqual([
            { month: "Jan", revenue: 10, cost: 4 },
            { month: "Feb", revenue: 22, cost: 9 },
        ]);
    });

    it("drops rows whose value column is not a finite number", () => {
        const rows = [
            { month: "Jan", revenue: "10", cost: "4" },
            { month: "Bad", revenue: "n/a", cost: "4" },
            { month: "NaN", revenue: "NaN", cost: "4" },
        ];
        expect(buildChartData(plan, rows)).toEqual([
            { month: "Jan", revenue: 10, cost: 4 },
        ]);
    });

    it("keeps string labels for the category column", () => {
        const rows = [{ month: "2026-09", revenue: "3", cost: "1" }];
        const [point] = buildChartData(plan, rows);
        expect(typeof point?.month).toBe("string");
        expect(point.month).toBe("2026-09");
    });
});

/* ---------- stable-prop regression (render-count guard) ---------- */

// Tracks the identity of the props recharts receives across renders. If the
// chart re-inlines `tick={{...}}`, `formatter={() => ...}` or grid objects,
// recharts sees a fresh reference on every render and re-renders the whole
// chart (the render storm). Hoisting them to module scope keeps references
// === stable, which is exactly what this test asserts.
const captures: { name: string; prop: [string, unknown] }[] = [];

function recordingComponent(name: string): ComponentType<Record<string, unknown>> {
    return function Recorded({ children, ...props }: Record<string, unknown>) {
        for (const key of ["tick", "tickFormatter", "formatter", "strokeDasharray"]) {
            if (key in props) captures.push({ name, prop: [key, props[key]] });
        }
        return (children ?? null) as ReactNode;
    };
}

vi.mock("recharts", () => ({
    Bar: recordingComponent("Bar"),
    BarChart: recordingComponent("BarChart"),
    CartesianGrid: recordingComponent("CartesianGrid"),
    Legend: recordingComponent("Legend"),
    Line: recordingComponent("Line"),
    LineChart: recordingComponent("LineChart"),
    ResponsiveContainer: recordingComponent("ResponsiveContainer"),
    Tooltip: recordingComponent("Tooltip"),
    XAxis: recordingComponent("XAxis"),
    YAxis: recordingComponent("YAxis"),
}));

const plan: ChartPlan = {
    kind: "line",
    category: "month",
    values: ["revenue", "cost"],
};
const rows = [
    { month: "Jan", revenue: "10", cost: "4" },
    { month: "Feb", revenue: "22", cost: "9" },
];

describe("ReportChart prop stability", () => {
    beforeEach(() => {
        captures.length = 0;
    });

    it("passes the same prop references on every render (hoisted, not inline)", () => {
        const chart = createElement(ReportChart, { plan, rows });

        renderToStaticMarkup(chart);
        renderToStaticMarkup(chart);

        const half = captures.length / 2;
        expect(captures.length).toBeGreaterThanOrEqual(2);

        const firstRun = captures.slice(0, half);
        const secondRun = captures.slice(half);

        expect(secondRun).toHaveLength(firstRun.length);
        for (let i = 0; i < firstRun.length; i++) {
            expect(firstRun[i].name).toBe(secondRun[i].name);
            expect(firstRun[i].prop[0]).toBe(secondRun[i].prop[0]);
            // The regression: an inline object/function is a *new* reference
            // each render; a hoisted constant is === identical.
            expect(secondRun[i].prop[1]).toBe(firstRun[i].prop[1]);
        }
    });
});