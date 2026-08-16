import { Contact, TrendingUp, Users } from "lucide-react";

import type { ModuleTab } from "@/components/dashboard/erp/module-tabs";

/** Section tabs shared by the CRM pages (Leads / Opportunities / Customers). */
export const crmTabs: ModuleTab[] = [
  { href: "/dashboard/erp/crm/leads", label: "Leads", icon: Contact },
  { href: "/dashboard/erp/crm/opportunities", label: "Opportunities", icon: TrendingUp },
  { href: "/dashboard/erp/crm/customers", label: "Customers", icon: Users },
];
