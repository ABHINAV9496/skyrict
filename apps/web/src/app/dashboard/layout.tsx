import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { DashboardShell } from "@/components/dashboard/dashboard-shell";
import { SESSION_COOKIE } from "@/lib/server/auth";
import { signinUrl } from "@/lib/server/urls";

export const metadata: Metadata = {
  robots: {
    index: false,
    follow: false,
  },
};

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const hasSession = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  if (!hasSession) {
    redirect(await signinUrl("Your session could not be established. Please sign in again."));
  }

  return <DashboardShell>{children}</DashboardShell>;
}
