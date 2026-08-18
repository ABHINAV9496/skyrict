"use client";

import { ModuleTabs } from "@/components/dashboard/erp/module-tabs";
import { crmTabs } from "@/components/dashboard/erp/crm/crm-tabs";

/**
 * Client-boundary wrapper for the CRM section tabs. The tab config carries
 * lucide icon components (functions), which cannot be passed as props from a
 * Server Component to a Client Component — so the icons stay inside this client
 * module and pages just render <CrmSectionTabs />.
 */
export function CrmSectionTabs() {
  return <ModuleTabs tabs={crmTabs} />;
}
