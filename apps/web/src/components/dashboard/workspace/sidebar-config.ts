import {
  BarChart3,
  Blocks,
  Contact,
  LayoutDashboard,
  Package,
  Plug,
  ShieldCheck,
  ShoppingCart,
  SlidersHorizontal,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Permission key that gates this item (absent = always visible inside its world). */
  permission?: string;
  soon?: boolean;
  tour?: string;
  /** Match only the exact href, never child paths (e.g. module overviews). */
  exact?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Workspace sidebar (non-module pages). Modules are entered from the Overview launchpad. */
export const workspaceNavGroups: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      {
        href: "/dashboard",
        label: "Overview",
        icon: LayoutDashboard,
        tour: "nav-overview",
      },
    ],
  },
  {
    label: "Manage",
    items: [
      {
        href: "/dashboard/roles",
        label: "Roles",
        icon: ShieldCheck,
        permission: "roles:read",
        tour: "nav-roles",
      },
      {
        href: "/dashboard/integrations",
        label: "Integrations",
        icon: Plug,
        soon: true,
        tour: "nav-integrations",
      },
    ],
  },
];

export const workspaceAccountItems: NavItem[] = [
  {
    href: "/dashboard/members",
    label: "Members",
    icon: Users,
    permission: "users:read",
    tour: "nav-members",
  },
  {
    href: "/dashboard/settings",
    label: "Settings",
    icon: SlidersHorizontal,
    permission: "settings:read",
    tour: "nav-settings",
  },
];

export const erpNavGroups: NavGroup[] = [
  {
    label: "Operations",
    items: [
      { href: "/dashboard/erp", label: "Dashboard", icon: LayoutDashboard, exact: true },
      { href: "/dashboard/erp/crm", label: "CRM", icon: Contact, permission: "erp.crm.read" },
      { href: "/dashboard/erp/sales", label: "Sales", icon: ShoppingCart, permission: "erp.sales.read" },
      { href: "/dashboard/erp/inventory", label: "Inventory", icon: Package, permission: "erp.inventory.read" },
      { href: "/dashboard/erp/finance", label: "Finance", icon: Wallet, permission: "erp.finance.read" },
      { href: "/dashboard/erp/hr", label: "HR", icon: Blocks, permission: "erp.hr.read" },
      { href: "/dashboard/erp/reports", label: "Reports", icon: BarChart3 },
    ],
  },
];

/** Keep only nav items whose permission the user holds (wildcard grants all). */
export function filterNavItemsByPermissions(
  items: NavItem[],
  permissions: string[],
): NavItem[] {
  const allowed = new Set(permissions);
  return items.filter((item) => {
    if (!item.permission) return true;
    return allowed.has("*") || allowed.has(item.permission);
  });
}

/** Filter nav groups, dropping groups that end up empty. */
export function filterNavGroupsByPermissions(
  groups: NavGroup[],
  permissions: string[],
): NavGroup[] {
  const result: NavGroup[] = [];
  for (const group of groups) {
    const items = filterNavItemsByPermissions(group.items, permissions);
    if (items.length > 0) result.push({ ...group, items });
  }
  return result;
}
