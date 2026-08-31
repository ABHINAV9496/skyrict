import { CalendarCheck2, Contact, ContactRound, LayoutDashboard, Search, Sparkles, TrendingUp, Users } from "lucide-react";

import type { ModuleTab } from "@/components/dashboard/erp/module-tabs";

/** Section tabs shared by the CRM pages. */
export const crmTabs: ModuleTab[] = [
  { href: "/dashboard/erp/crm/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/erp/crm/leads", label: "Leads", icon: Contact },
  { href: "/dashboard/erp/crm/opportunities", label: "Opportunities", icon: TrendingUp },
  { href: "/dashboard/erp/crm/customers", label: "Customers", icon: Users },
  { href: "/dashboard/erp/crm/contacts", label: "Contacts", icon: ContactRound },
  { href: "/dashboard/erp/crm/activities", label: "Activities", icon: CalendarCheck2 },
  { href: "/dashboard/erp/crm/ai", label: "AI Insights", icon: Sparkles },
  { href: "/dashboard/erp/crm/search", label: "Search", icon: Search },
];
