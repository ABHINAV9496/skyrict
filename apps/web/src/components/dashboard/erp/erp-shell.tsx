"use client";

import { useCallback, useEffect, useState } from "react";

import { AppSidebar } from "@/components/dashboard/workspace/app-sidebar";
import { Topbar } from "@/components/dashboard/workspace/topbar";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import {
  erpNavGroups,
  filterNavGroupsByPermissions,
} from "@/components/dashboard/workspace/sidebar-config";
import { useModuleAccess } from "@/lib/access/modules";

const COLLAPSED_KEY = "skyrict:sidebar:collapsed";

/**
 * The ERP "world": a conventional operations application. The sidebar shows the
 * ERP sub-modules (CRM, Sales, Inventory, Finance, HR, Reports) and each one is
 * a real page — not a card buried inside a single-page route.
 */
export function ErpShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { status, permissions } = useModuleAccess();

  useEffect(() => {
    setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "true");
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((value) => {
      localStorage.setItem(COLLAPSED_KEY, String(!value));
      return !value;
    });
  }, []);

  const navGroups =
    status === "ready"
      ? filterNavGroupsByPermissions(erpNavGroups, permissions)
      : erpNavGroups;

  return (
    <ModuleAccessBoundary module="erp">
      <div className="flex h-dvh overflow-hidden bg-background theme-erp">
        <AppSidebar
          collapsed={collapsed}
          mobileOpen={mobileOpen}
          onToggleCollapsed={toggleCollapsed}
          onCloseMobile={() => setMobileOpen(false)}
          navGroups={navGroups}
          accountItems={[]}
          brandHref="/dashboard/erp"
          logoTone="erp"
          showBackToOverview
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onOpenMenu={() => setMobileOpen(true)} />
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-6xl px-4 py-6 lg:px-6 lg:py-8">{children}</div>
          </main>
        </div>
      </div>
    </ModuleAccessBoundary>
  );
}
