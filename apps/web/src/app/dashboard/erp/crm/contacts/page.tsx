import { ContactRound } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { ContactsTable } from "@/components/dashboard/erp/crm/contacts-table";

export default function CrmContactsPage() {
  return (
    <RequirePermission permission="erp.crm.read">
      <div className="space-y-6">
        <PageHeader
          title="Contacts"
          description="The people on your customer accounts. Primary contacts anchor the relationship timeline."
          icon={ContactRound}
        />
        <ContactsTable />
      </div>
    </RequirePermission>
  );
}
