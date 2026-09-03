/**
 * Widget registry for the ERP dashboard customizer.
 *
 * Each widget maps an ID to a React component, a default column span,
 * and optional permission keys.  The WidgetGrid renderer reads this
 * registry to decide what to render and how to lay it out.
 */

import type { ComponentType } from "react";

import { AttentionStrip } from "@/components/dashboard/erp/attention-strip";
import { CrossModuleKpis } from "@/components/dashboard/erp/cross-module-kpis";
import { DigestCard } from "@/components/dashboard/erp/digest-card";
import { ErpOverviewSummary } from "@/components/dashboard/erp/erp-overview-summary";
import { ErpReportsKpis } from "@/components/dashboard/erp/erp-reports-kpis";
import { ModuleQuickLinks } from "@/components/dashboard/erp/module-quick-links";

export interface WidgetDefinition {
  /** Unique identifier - matches the layout JSONB `id` field. */
  id: string;
  /** Display title shown in the customize panel. */
  title: string;
  /** Short description for the customize panel tooltip. */
  description: string;
  /** The React component to render. */
  component: ComponentType;
  /** Default grid column span (1-4). */
  defaultCols: 1 | 2 | 3 | 4;
  /** Minimum column span (for resize). */
  minCols: 1 | 2;
  /** Maximum column span (for resize). */
  maxCols: 4;
  /** Grouping for the customize panel. */
  group: "overview" | "modules" | "insights";
  /** Permission keys required to see this widget. Empty = visible to all. */
  permissions?: string[];
}

/**
 * Canonical list of available widgets. Order here prioritizes:
 * 1. Attention & Exceptions strip
 * 2. Cross-Module KPI Snapshot (Finance & Operations clusters)
 * 3. Module Quick Links
 * 4. Collapsible Intelligence Digest
 */
export const WIDGET_REGISTRY: WidgetDefinition[] = [
  {
    id: "attention_strip",
    title: "Attention Needed",
    description: "Urgent decision items across inventory, finance, sales, and CRM.",
    component: AttentionStrip,
    defaultCols: 4,
    minCols: 2,
    maxCols: 4,
    group: "overview",
  },
  {
    id: "cross_module_kpis",
    title: "Cross-Module Snapshot",
    description: "Grouped financial and operational KPIs.",
    component: CrossModuleKpis,
    defaultCols: 4,
    minCols: 2,
    maxCols: 4,
    group: "overview",
  },
  {
    id: "module_quick_links",
    title: "Module Quick Links",
    description: "Quick navigation to CRM, Orders, Inventory, and more.",
    component: ModuleQuickLinks,
    defaultCols: 4,
    minCols: 2,
    maxCols: 4,
    group: "modules",
  },
  {
    id: "ai_digest",
    title: "Intelligence Digest",
    description: "Daily cross-module AI summary of key signals.",
    component: DigestCard,
    defaultCols: 4,
    minCols: 2,
    maxCols: 4,
    group: "insights",
  },
  {
    id: "erp_overview",
    title: "At a Glance (Legacy)",
    description: "Live open pipeline value and open orders count.",
    component: ErpOverviewSummary,
    defaultCols: 4,
    minCols: 2,
    maxCols: 4,
    group: "overview",
  },
  {
    id: "reports_kpis",
    title: "Report KPIs (Legacy)",
    description: "Key performance indicators from ERP reports.",
    component: ErpReportsKpis,
    defaultCols: 3,
    minCols: 1,
    maxCols: 4,
    group: "overview",
    permissions: ["erp.reports.read"],
  },
];

/** Lookup a widget by ID. Returns undefined if not found. */
export function getWidget(id: string): WidgetDefinition | undefined {
  return WIDGET_REGISTRY.find((w) => w.id === id);
}

/** Default 4-widget ERP layout in priority hierarchy order. */
const DEFAULT_PRIMARY_WIDGET_IDS = ["attention_strip", "cross_module_kpis", "module_quick_links", "ai_digest"];

/** Return the default layout (prioritized default widgets, order and sizes). */
export function getDefaultLayout(): { id: string; order: number; cols: 1 | 2 | 3 | 4; visible: boolean }[] {
  return DEFAULT_PRIMARY_WIDGET_IDS.map((id, index) => {
    const widget = getWidget(id);
    return {
      id,
      order: index,
      cols: widget ? widget.defaultCols : 4,
      visible: true,
    };
  });
}

/** Filter widgets by a set of permission keys. */
export function filterWidgetsByPermissions(
  layout: { id: string; order: number; cols: 1 | 2 | 3 | 4; visible: boolean }[],
  grantedPermissions: string[],
): { id: string; order: number; cols: 1 | 2 | 3 | 4; visible: boolean }[] {
  return layout.filter((item) => {
    const widget = getWidget(item.id);
    if (!widget) return false;
    if (!widget.permissions || widget.permissions.length === 0) return true;
    return widget.permissions.some((p) => grantedPermissions.includes(p));
  });
}
