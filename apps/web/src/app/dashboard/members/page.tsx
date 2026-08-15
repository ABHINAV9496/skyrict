import MembersClient from "@/app/dashboard/members/members";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";

export default function MembersPage() {
  return (
    <RequirePermission permission="users:read">
      <MembersClient />
    </RequirePermission>
  );
}
