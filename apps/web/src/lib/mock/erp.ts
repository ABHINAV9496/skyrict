/**
 * Mock ERP data for the frontend-only ERP world.
 *
 * Each sub-module exposes a lightweight table shape - `columns` drives the
 * headers, `rows` are plain objects - so the shared DataTable renders without
 * knowing what domain it is showing. Swap these behind stub API routes when
 * the core service grows real endpoints.
 */

export interface TableColumn {
    key: string;
    label: string;
    align?: "left" | "right";
}

export interface TablePayload {
    columns: TableColumn[];
    rows: Record<string, string | number | null>[];
}

export interface Kpi {
    label: string;
    value: string;
    delta: string;
    positive: boolean;
}

export const reportsKpis: Kpi[] = [
    {
        label: "Revenue this month",
        value: "$186,400",
        delta: "+12.4%",
        positive: true,
    },
    { label: "Orders", value: "1,284", delta: "+8.1%", positive: true },
    { label: "Gross margin", value: "34.2%", delta: "+1.6 pt", positive: true },
    {
        label: "On-hand inventory",
        value: "$412,300",
        delta: "-2.3%",
        positive: false,
    },
    {
        label: "Avg. deal size",
        value: "$31,800",
        delta: "+5.9%",
        positive: true,
    },
    { label: "Headcount", value: "47", delta: "±0", positive: true },
];
