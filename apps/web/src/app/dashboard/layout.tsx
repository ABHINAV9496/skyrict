import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { signinUrl } from "@/lib/server/urls";
import { SESSION_COOKIE } from "@/lib/server/auth";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const hasSession = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  if (!hasSession) {
    redirect(await signinUrl("Your session could not be established. Please sign in again."));
  }

  return (
    <div>
      <nav>
        <span>Skyrict Dashboard</span>
      </nav>
      <main>{children}</main>
    </div>
  );
}
