"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useModuleAccess } from "@/lib/access/modules";
import { ListPageSkeleton } from "@/components/ui/page-skeletons";

/**
 * Fail-closed route guard for workspace pages. While access permissions load
 * it renders a neutral skeleton (never page content); if the user lacks the
 * required permission - or access cannot be verified - it redirects to the
 * overview so a restricted route is never revealed.
 */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: React.ReactNode;
}) {
  const { status, permissions } = useModuleAccess();
  const router = useRouter();

  const allowed =
    status === "ready" &&
    (permissions.includes("*") || permissions.includes(permission));

  useEffect(() => {
    if (status === "loading") return;
    if (!allowed) router.replace("/dashboard");
  }, [status, allowed, router]);

  if (status === "loading") return <ListPageSkeleton />;
  if (!allowed) return null;
  return <>{children}</>;
}
