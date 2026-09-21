import { normalizeDashboardPath } from "@/lib/dashboard-path";
import {
    Activity,
    AlertTriangle,
    ArrowLeftRight,
    BadgeDollarSign,
    BarChart3,
    BellRing,
    Blocks,
    BookOpen,
    Building2,
    Calendar,
    CalendarClock,
    CalendarDays,
    ClipboardCheck,
    Coins,
    Contact,
    ContactRound,
    CreditCard,
    FileText,
    FolderOpen,
    LayoutDashboard,
    Layers,
    NotebookPen,
    Package,
    Plug,
    Receipt,
    ReceiptText,
    Search,
    ScrollText,
    ShieldCheck,
    ShieldAlert,
    ShoppingCart,
    SlidersHorizontal,
    Sparkles,
    TrendingDown,
    TrendingUp,
    UserPlus,
    UserRound,
    Users,
    Wallet,
    Warehouse,
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
    /** Sub-navigation rendered as indented rows under a collapsible toggle row. */
    children?: NavItem[];
}

export interface NavGroup {
    label: string;
    items: NavItem[];
    /** Collapsible groups render their label as a toggle that opens the indented sub-items. */
    collapsible?: boolean;
}

/**
 * Compare the active path against a nav href. Hrefs use the canonical public
 * workspace URL (no `/dashboard` prefix, e.g. `/settings`), and `usePathname()`
 * reports the same public form, so normalize both sides before comparing via
 * the internal `/dashboard/*` form. Non-exact items also match any path nested
 * under their href; module roots and overview children should set `exact: true`
 * so they do not light up for sibling routes (e.g. Documents Overview vs All
 * documents).
 */
export function isSidebarItemActive(
    pathname: string,
    item: Pick<NavItem, "href" | "exact">,
): boolean {
    // Normalize both sides: the browser path may already be internal
    // (`/dashboard/...`) in tests or edge flows.
    const normalizedPath = normalizeDashboardPath(pathname);
    const normalizedHref = normalizeDashboardPath(item.href);
    const { exact } = item;
    if (normalizedHref === "/dashboard" || exact) {
        return normalizedPath === normalizedHref;
    }
    return (
        normalizedPath === normalizedHref ||
        normalizedPath.startsWith(`${normalizedHref}/`)
    );
}

/** Workspace sidebar (non-module pages). Modules are entered from the Overview launchpad. */
export const workspaceNavGroups: NavGroup[] = [
    {
        label: "Workspace",
        items: [
            {
                href: "/",
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
                href: "/roles",
                label: "Roles",
                icon: ShieldCheck,
                permission: "roles:read",
                tour: "nav-roles",
            },
            {
                href: "/integrations",
                label: "Integrations",
                icon: Plug,
                soon: true,
                tour: "nav-integrations",
            },
            {
                href: "/settings/notifications",
                label: "Notifications",
                icon: BellRing,
                tour: "nav-notifications",
            },
            {
                href: "/settings/billing",
                label: "Billing",
                icon: CreditCard,
                tour: "nav-billing",
            },
        ],
    },
];

export const workspaceAccountItems: NavItem[] = [
    {
        href: "/dashboard/invite",
        label: "Invite team",
        icon: UserPlus,
        permission: "invitations:send",
        tour: "nav-invite",
    },
    {
        href: "/members",
        label: "Members",
        icon: Users,
        permission: "users:read",
        tour: "nav-members",
    },
    {
        href: "/settings",
        label: "Settings",
        icon: SlidersHorizontal,
        tour: "nav-settings",
        // Exact only: Billing and Notifications are separate top-level rows that
        // live under /dashboard/settings/*. Without this they prefix-match
        // Settings too, lighting up two rows at once.
        exact: true,
    },
];

export const erpNavGroups: NavGroup[] = [
    {
        label: "Operations",
        items: [
            {
                href: "/erp",
                label: "Dashboard",
                icon: LayoutDashboard,
                exact: true,
            },
            {
                // The parent row lands on a REAL page, never a redirect stub:
                // `/dashboard/erp/crm` is a `redirect()` into `/crm/overview`, so
                // linking there cost a full extra round trip on every click.
                // Every other module parent already renders its landing page.
                href: "/erp/crm/overview",
                label: "CRM",
                icon: Contact,
                permission: "erp.crm.read",
                exact: true,
                children: [
                    {
                        href: "/erp/crm/overview",
                        label: "Overview",
                        icon: LayoutDashboard,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/leads",
                        label: "Leads",
                        icon: Contact,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/opportunities",
                        label: "Opportunities",
                        icon: TrendingUp,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/customers",
                        label: "Customers",
                        icon: Users,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/contacts",
                        label: "Contacts",
                        icon: ContactRound,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/activities",
                        label: "Activities",
                        icon: CalendarClock,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/ai",
                        label: "AI Insights",
                        icon: Sparkles,
                        permission: "erp.crm.read",
                    },
                    {
                        href: "/erp/crm/search",
                        label: "Search",
                        icon: Search,
                        permission: "erp.crm.read",
                    },
                ],
            },
            {
                href: "/erp/orders",
                label: "Orders",
                icon: ShoppingCart,
                permission: "erp.sales.read",
            },
            {
                href: "/erp/inventory",
                label: "Inventory",
                icon: Package,
                permission: "erp.inventory.read",
                exact: true,
                children: [
                    {
                        href: "/erp/inventory/products",
                        label: "Products",
                        icon: Package,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/warehouses",
                        label: "Warehouses",
                        icon: Warehouse,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/stock",
                        label: "Stock",
                        icon: Layers,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/movements",
                        label: "Movements",
                        icon: ArrowLeftRight,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/alerts",
                        label: "Alerts",
                        icon: BellRing,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/suggestions",
                        label: "AI Suggestions",
                        icon: ShoppingCart,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/anomalies",
                        label: "Anomalies",
                        icon: AlertTriangle,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/forecast",
                        label: "Forecast",
                        icon: Calendar,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/abc",
                        label: "ABC Classification",
                        icon: BarChart3,
                        permission: "erp.inventory.read",
                    },
                    {
                        href: "/erp/inventory/health",
                        label: "Stock Health",
                        icon: Activity,
                        permission: "erp.inventory.read",
                    },
                ],
            },
            {
                href: "/erp/hr",
                label: "HR",
                icon: Blocks,
                permission: "erp.hr.read",
                exact: true,
                children: [
                    {
                        href: "/erp/hr/employees",
                        label: "Employees",
                        icon: UserRound,
                        permission: "erp.hr.read",
                    },
                    {
                        href: "/erp/hr/departments",
                        label: "Departments",
                        icon: Building2,
                        permission: "erp.hr.read",
                    },
                    {
                        href: "/erp/hr/leave",
                        label: "Leave",
                        icon: CalendarDays,
                        permission: "erp.hr.read",
                    },
                    {
                        href: "/erp/hr/attendance",
                        label: "Attendance",
                        icon: CalendarClock,
                        permission: "erp.hr.read",
                    },
                    {
                        href: "/erp/hr/data-quality",
                        label: "Data quality",
                        icon: ClipboardCheck,
                        permission: "erp.hr.read",
                    },
                    {
                        href: "/erp/hr/ai-alerts",
                        label: "AI alerts",
                        icon: ShieldAlert,
                        permission: "erp.hr.ai.read",
                    },
                    {
                        href: "/erp/hr/attrition",
                        label: "Attrition",
                        icon: TrendingDown,
                        permission: "erp.hr.ai.read",
                    },
                    {
                        href: "/erp/hr/planning",
                        label: "Planning",
                        icon: TrendingUp,
                        permission: "erp.hr.ai.planning",
                    },
                    {
                        href: "/erp/hr/compliance",
                        label: "Compliance",
                        icon: ShieldCheck,
                        permission: "erp.hr.ai.read",
                    },
                    {
                        href: "/erp/hr/correlation",
                        label: "Leave · pay correlation",
                        icon: Activity,
                        permission: "erp.hr.ai.read",
                    },
                ],
            },
            {
                href: "/erp/finance",
                label: "Finance",
                icon: Wallet,
                permission: "erp.finance.read",
                exact: true,
                children: [
                    {
                        href: "/erp/finance/accounts",
                        label: "Ledger",
                        icon: BookOpen,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/journal-entries",
                        label: "Journal Entries",
                        icon: NotebookPen,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/fiscal-periods",
                        label: "Fiscal Periods",
                        icon: CalendarDays,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/invoices",
                        label: "Invoices",
                        icon: ReceiptText,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/statements",
                        label: "Statements",
                        icon: BarChart3,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/controls",
                        label: "Planning & Policy",
                        icon: SlidersHorizontal,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/audit-log",
                        label: "Audit Log",
                        icon: ScrollText,
                        permission: "erp.finance.read",
                    },
                    {
                        href: "/erp/finance/ai-docs",
                        label: "AI Docs",
                        icon: Sparkles,
                        permission: "erp.finance.ai.read",
                    },
                    {
                        href: "/erp/finance/settings",
                        label: "Settings",
                        icon: SlidersHorizontal,
                        permission: "erp.finance.read",
                    },
                ],
            },
            {
                href: "/erp/payroll",
                label: "Payroll",
                icon: Receipt,
                permission: "erp.payroll.read",
                exact: true,
                children: [
                    {
                        href: "/erp/payroll/runs",
                        label: "Runs",
                        icon: BadgeDollarSign,
                        permission: "erp.payroll.read",
                    },
                    {
                        href: "/erp/payroll/reviews",
                        label: "Reviews",
                        icon: ClipboardCheck,
                        permission: "erp.payroll.approve",
                    },
                    {
                        href: "/erp/payroll/compensation",
                        label: "Compensation",
                        icon: Coins,
                        permission: "erp.payroll.read",
                    },
                    {
                        href: "/erp/payroll/settings",
                        label: "Settings",
                        icon: SlidersHorizontal,
                        permission: "erp.payroll.read",
                    },
                    {
                        href: "/erp/payroll/automation",
                        label: "Automation",
                        icon: CalendarClock,
                        permission: "erp.payroll.ai.read",
                    },
                    {
                        href: "/erp/payroll/anomalies",
                        label: "Payroll anomalies",
                        icon: AlertTriangle,
                        permission: "erp.payroll.ai.read",
                    },
                ],
            },
            {
                href: "/erp/documents",
                label: "Documents",
                icon: FileText,
                permission: "erp.documents.read",
                exact: true,
                children: [
                    {
                        href: "/erp/documents",
                        label: "Overview",
                        icon: LayoutDashboard,
                        permission: "erp.documents.read",
                        exact: true,
                    },
                    {
                        href: "/erp/documents/list",
                        label: "All documents",
                        icon: FolderOpen,
                        permission: "erp.documents.read",
                    },
                ],
            },
            {
                href: "/erp/reports",
                label: "Reports",
                icon: BarChart3,
            },
        ],
    },
];

/** Keep only nav items whose permission the user holds (wildcard grants all). */
export function filterNavItemsByPermissions(
    items: NavItem[],
    permissions: string[],
): NavItem[] {
    const allowed = new Set(permissions);
    const result: NavItem[] = [];
    for (const item of items) {
        if (
            item.permission &&
            !allowed.has("*") &&
            !allowed.has(item.permission)
        ) {
            continue;
        }
        if (item.children) {
            const children = filterNavItemsByPermissions(
                item.children,
                permissions,
            );
            if (children.length === 0) continue;
            result.push({ ...item, children });
        } else {
            result.push(item);
        }
    }
    return result;
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
