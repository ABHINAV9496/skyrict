/**
 * Mock ERP data for the frontend-only ERP world.
 *
 * Each sub-module exposes a lightweight table shape — `columns` drives the
 * headers, `rows` are plain objects — so the shared DataTable renders without
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

export const inventoryData: TablePayload = {
  columns: [
    { key: "sku", label: "SKU" },
    { key: "name", label: "Item" },
    { key: "warehouse", label: "Warehouse" },
    { key: "quantity", label: "On hand", align: "right" },
    { key: "reorder", label: "Reorder at", align: "right" },
  ],
  rows: [
    { sku: "SKU-1001", name: "Steel bracket 4×4", warehouse: "East DC", quantity: 482, reorder: 150 },
    { sku: "SKU-1002", name: "Aluminum extrusion 2m", warehouse: "West DC", quantity: 96, reorder: 200 },
    { sku: "SKU-1003", name: "Hex bolt M8 (bag 50)", warehouse: "East DC", quantity: 1240, reorder: 500 },
    { sku: "SKU-1004", name: "Rubber gasket 6in", warehouse: "West DC", quantity: 41, reorder: 120 },
    { sku: "SKU-1005", name: "Drive belt 12mm", warehouse: "Central DC", quantity: 310, reorder: 100 },
    { sku: "SKU-1006", name: "LED module 24V", warehouse: "Central DC", quantity: 88, reorder: 90 },
  ],
};

export const financeData: TablePayload = {
  columns: [
    { key: "date", label: "Date" },
    { key: "description", label: "Description" },
    { key: "category", label: "Category" },
    { key: "type", label: "Type" },
    { key: "amount", label: "Amount", align: "right" },
  ],
  rows: [
    { date: "2026-07-30", description: "Invoice INV-2210 paid", category: "Revenue", type: "Inflow", amount: 18240 },
    { date: "2026-07-30", description: "Warehouse rent July", category: "Facilities", type: "Outflow", amount: 6500 },
    { date: "2026-07-29", description: "Payroll run", category: "Payroll", type: "Outflow", amount: 41300 },
    { date: "2026-07-28", description: "Invoice INV-2205 paid", category: "Revenue", type: "Inflow", amount: 9200 },
    { date: "2026-07-27", description: "Supplier PO-882", category: "Procurement", type: "Outflow", amount: 15750 },
    { date: "2026-07-26", description: "Invoice INV-2198 paid", category: "Revenue", type: "Inflow", amount: 48900 },
  ],
};

export const hrData: TablePayload = {
  columns: [
    { key: "name", label: "Name" },
    { key: "role", label: "Role" },
    { key: "department", label: "Department" },
    { key: "status", label: "Status" },
    { key: "start", label: "Started" },
  ],
  rows: [
    { name: "Priya Shah", role: "Sales Lead", department: "Sales", status: "Active", start: "2024-03-11" },
    { name: "Marcus Chen", role: "Account Executive", department: "Sales", status: "Active", start: "2024-08-02" },
    { name: "Dana Kim", role: "Operations Manager", department: "Operations", status: "Active", start: "2023-11-20" },
    { name: "Sam Osei", role: "Software Engineer", department: "Engineering", status: "Active", start: "2025-01-14" },
    { name: "Elena Cruz", role: "Financial Analyst", department: "Finance", status: "On leave", start: "2024-05-06" },
  ],
};

export interface Kpi {
  label: string;
  value: string;
  delta: string;
  positive: boolean;
}

export const reportsKpis: Kpi[] = [
  { label: "Revenue this month", value: "$186,400", delta: "+12.4%", positive: true },
  { label: "Orders", value: "1,284", delta: "+8.1%", positive: true },
  { label: "Gross margin", value: "34.2%", delta: "+1.6 pt", positive: true },
  { label: "On-hand inventory", value: "$412,300", delta: "-2.3%", positive: false },
  { label: "Avg. deal size", value: "$31,800", delta: "+5.9%", positive: true },
  { label: "Headcount", value: "47", delta: "±0", positive: true },
];
