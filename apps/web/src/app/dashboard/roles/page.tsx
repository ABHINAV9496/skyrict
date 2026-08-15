import RolesClient from "@/app/dashboard/roles/roles";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";

export default function RolesPage() {
  return (
    <RequirePermission permission="roles:read">
      <RolesClient />
    </RequirePermission>
  );
}
