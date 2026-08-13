"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AppSidebar } from "@/components/dashboard/app-sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { ProductTour } from "@/components/dashboard/tour/product-tour";
import {
  filterNavGroupsByPermissions,
  filterNavItemsByPermissions,
  workspaceAccountItems,
  workspaceNavGroups,
} from "@/components/dashboard/sidebar-config";
import { useModuleAccess } from "@/lib/access/modules";

const COLLAPSED_KEY = "skyrict:sidebar:collapsed";

export function DashboardShell({ children }: { children: React.ReactNode }) {
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
    <div className="flex h-dvh overflow-hidden bg-background">
      <AppSidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapsed={toggleCollapsed}
        onCloseMobile={() => setMobileOpen(false)}
        navGroups={navGroups}
        accountItems={accountItems}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMobileOpen(true)} />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl px-4 py-6 lg:px-6 lg:py-8">{children}</div>
        </main>
      </div>
      <ProductTour />
    </div>
  );
}
