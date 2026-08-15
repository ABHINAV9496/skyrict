import InviteClient from "@/app/dashboard/invite/invite";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";

export default function InvitePage() {
  return (
    <RequirePermission permission="invitations:send">
      <InviteClient />
    </RequirePermission>
  );
}
