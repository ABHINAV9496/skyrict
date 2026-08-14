"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { usePathname } from "next/navigation";

import { AppSidebar } from "@/components/dashboard/workspace/app-sidebar";
import { Topbar } from "@/components/dashboard/workspace/topbar";
import { ProductTour } from "@/components/dashboard/tour/product-tour";
import {
  filterNavGroupsByPermissions,
  filterNavItemsByPermissions,
  workspaceAccountItems,
  workspaceNavGroups,
} from "@/components/dashboard/workspace/sidebar-config";
import { useModuleAccess } from "@/lib/access/modules";
import { normalizeDashboardPath } from "@/lib/dashboard-path";
import { cn } from "@/lib/utils";

const COLLAPSED_KEY = "skyrict:sidebar:collapsed";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { status, permissions } = useModuleAccess();
  const pathname = usePathname();

  // The Roles screen manages its own viewport height (internal panel
  // scrolling only), so `main` must not become a page scroll container there.
  const isFixedViewportPage = normalizeDashboardPath(pathname) === "/dashboard/roles";

  useEffect(() => {
    setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "true");
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((value) => {
      localStorage.setItem(COLLAPSED_KEY, String(!value));
      return !value;
    });
  }, []);

  // Gate Members/Roles/Settings behind their permission keys once access is known.
  const navGroups = useMemo(
    () => (status === "ready" ? filterNavGroupsByPermissions(workspaceNavGroups, permissions) : workspaceNavGroups),
    [status, permissions],
  );
  const accountItems = useMemo(
    () => (status === "ready" ? filterNavItemsByPermissions(workspaceAccountItems, permissions) : workspaceAccountItems),
    [status, permissions],
  );

  return (
    <div className="flex h-screen overflow-hidden bg-background [@supports(height:100dvh)]:h-dvh">
      <AppSidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapsed={toggleCollapsed}
        onCloseMobile={() => setMobileOpen(false)}
        navGroups={navGroups}
        accountItems={accountItems}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMobileOpen(true)} />
        <main
          className={cn(
            "flex min-h-0 flex-1 flex-col overflow-x-hidden",
            isFixedViewportPage ? "overflow-hidden" : "overflow-y-auto",
          )}
        >
          <div className="mx-auto flex w-full min-h-0 max-w-6xl flex-1 flex-col px-4 py-6 lg:px-6 lg:py-8">
            {children}
          </div>
        </main>
      </div>
      <ProductTour />
    </div>
  );
}
