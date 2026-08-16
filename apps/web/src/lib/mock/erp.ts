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

export const crmData: TablePayload = {
  columns: [
    { key: "name", label: "Name" },
    { key: "company", label: "Company" },
    { key: "email", label: "Email" },
    { key: "stage", label: "Stage" },
    { key: "owner", label: "Owner" },
    { key: "value", label: "Value", align: "right" },
  ],
  rows: [
    { name: "Ava Whitmore", company: "Northwind Traders", email: "ava@northwind.dev", stage: "Qualified", owner: "Priya Shah", value: 42000 },
    { name: "Liam Okafor", company: "Brightline Labs", email: "liam@brightline.io", stage: "Proposal", owner: "Marcus Chen", value: 87500 },
    { name: "Sofia Reyes", company: "Harbor & Co", email: "sofia@harborco.com", stage: "Negotiation", owner: "Priya Shah", value: 124000 },
    { name: "Noah Berg", company: "Alpine Supply", email: "noah@alpinesupply.net", stage: "Lead", owner: "Dana Kim", value: 18500 },
    { name: "Mia Laurent", company: "Cascade Works", email: "mia@cascadeworks.io", stage: "Qualified", owner: "Marcus Chen", value: 63000 },
    { name: "Ethan Brooks", company: "Vertex Robotics", email: "ethan@vertexrobotics.com", stage: "Closed won", owner: "Dana Kim", value: 210000 },
    { name: "Zara Haddad", company: "Pavilion Group", email: "zara@paviliongroup.co", stage: "Lead", owner: "Priya Shah", value: 9200 },
  ],
};

export const salesData: TablePayload = {
  columns: [
    { key: "order", label: "Order" },
    { key: "customer", label: "Customer" },
    { key: "status", label: "Status" },
    { key: "date", label: "Date" },
    { key: "amount", label: "Amount", align: "right" },
  ],
  rows: [
    { order: "SO-1042", customer: "Northwind Traders", status: "Shipped", date: "2026-07-28", amount: 18240 },
    { order: "SO-1043", customer: "Brightline Labs", status: "Processing", date: "2026-07-29", amount: 3475 },
    { order: "SO-1044", customer: "Harbor & Co", status: "Delivered", date: "2026-07-25", amount: 9200 },
    { order: "SO-1045", customer: "Alpine Supply", status: "Pending", date: "2026-07-30", amount: 5110 },
    { order: "SO-1046", customer: "Cascade Works", status: "Shipped", date: "2026-07-29", amount: 27650 },
    { order: "SO-1047", customer: "Vertex Robotics", status: "Delivered", date: "2026-07-22", amount: 48900 },
    { order: "SO-1048", customer: "Pavilion Group", status: "Processing", date: "2026-07-30", amount: 1830 },
  ],
};

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
