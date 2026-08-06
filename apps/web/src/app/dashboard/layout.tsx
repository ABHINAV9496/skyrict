import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SESSION_COOKIE } from "@/lib/server/auth";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const hasSession = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  if (!hasSession) redirect("/login");

  return (
    <div>
      <nav>
        <span>Skyrict Dashboard</span>
      </nav>
      <main>{children}</main>
    </div>
  );
}
