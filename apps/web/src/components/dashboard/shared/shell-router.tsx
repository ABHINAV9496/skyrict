"use client";

import { usePathname } from "next/navigation";

import { AgentsShell } from "@/components/dashboard/agents/agents-shell";
import { DashboardShell } from "@/components/dashboard/workspace/dashboard-shell";
import { ErpShell } from "@/components/dashboard/erp/erp-shell";
import { IntelligenceShell } from "@/components/dashboard/intelligence/intelligence-shell";
import type { ModuleKey } from "@/lib/access/modules";
import { normalizeDashboardPath } from "@/lib/dashboard-path";

/**
 * Picks the world that wraps the current page. Each module renders inside its
 * own distinct chrome — chat for AI Agents, a conventional app for ERP, and a
 * search engine for Intelligence. Everything else stays in the workspace shell.
 */
export function ShellRouter({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const moduleKey = detectModule(pathname);

  if (moduleKey === "agents") return <AgentsShell>{children}</AgentsShell>;
  if (moduleKey === "erp") return <ErpShell>{children}</ErpShell>;
  if (moduleKey === "intelligence") return <IntelligenceShell>{children}</IntelligenceShell>;
  return <DashboardShell>{children}</DashboardShell>;
}

function detectModule(pathname: string): ModuleKey | null {
  const normalized = normalizeDashboardPath(pathname);
  if (normalized === "/dashboard/erp" || normalized.startsWith("/dashboard/erp/")) return "erp";
  if (normalized === "/dashboard/agents" || normalized.startsWith("/dashboard/agents/")) {
    return "agents";
  }
  if (
    normalized === "/dashboard/intelligence" ||
    normalized.startsWith("/dashboard/intelligence/")
  ) {
    return "intelligence";
  }
  return null;
}
