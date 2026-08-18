"use client";

import Link from "next/link";
import { ArrowLeft, LoaderCircle, Lock, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useModuleAccess, type ModuleKey } from "@/lib/access/modules";

const MODULE_LABEL: Record<ModuleKey, string> = {
  erp: "Business Operations",
  agents: "AI Agents",
  intelligence: "Market Intelligence",
};

/** Minimal loading indicator while permissions resolve. */
export function ModuleLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background">
      <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}

function ModuleNotice({
  title,
  description,
  icon: Icon,
  action,
}: {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <Icon aria-hidden="true" className="size-5" />
        </div>
        <h1 className="mt-5 font-display text-xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p>
        <div className="mt-6">{action ?? <LoaderCircle aria-hidden="true" className="mx-auto size-5 animate-spin text-primary" />}</div>
      </div>
    </div>
  );
}

export function ModuleAccessDenied({ module }: { module: ModuleKey }) {
  return (
    <ModuleNotice
      title={`No access to ${MODULE_LABEL[module]}`}
      description="Your roles don't include permission for this space. Ask a workspace owner to update your role or sign in with an account that has access."
      icon={Lock}
      action={
        <Button asChild>
          <Link href="/dashboard">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to overview
          </Link>
        </Button>
      }
    />
  );
}

const PERMISSION_LABEL: Record<string, string> = {
  "erp.hr.read": "HR",
  "erp.payroll.read": "Payroll",
};

/** Blocked state for a user who can reach a module but not a specific area. */
export function ModulePermissionDenied({ permission }: { permission: string }) {
  const label = PERMISSION_LABEL[permission] ?? "this area";
  return (
    <ModuleNotice
      title={`No access to ${label}`}
      description="Your roles don't include permission for this area. Ask a workspace owner to update your role or sign in with an account that has access."
      icon={Lock}
      action={
        <Button asChild>
          <Link href="/dashboard/erp">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to overview
          </Link>
        </Button>
      }
    />
  );
}

export function ModuleAccessError({ module }: { module: ModuleKey }) {
  return (
    <ModuleNotice
      title="Couldn't verify access"
      description={`We couldn't load your permissions for ${MODULE_LABEL[module]}. Check your connection and try again.`}
      icon={ShieldAlert}
      action={
        <Button asChild variant="outline">
          <Link href="/dashboard">Back to overview</Link>
        </Button>
      }
    />
  );
}

/**
 * Wraps a module world with the access check. Renders a themed skeleton while
 * permissions load, then either the module's chrome or an access-denied panel.
 * An optional `permission` narrows the check to a specific key (e.g. a
 * sub-module page inside an accessible world); when absent, only the module
 * gate applies.
 */
export function ModuleAccessBoundary({
  module,
  permission,
  children,
}: {
  module: ModuleKey;
  permission?: string;
  children: React.ReactNode;
}) {
  const { status, access, permissions } = useModuleAccess();

  if (status === "loading") return <ModuleLoading />;
  if (status === "error") return <ModuleAccessError module={module} />;
  if (!access[module]) return <ModuleAccessDenied module={module} />;
  if (
    permission &&
    !(permissions.includes("*") || permissions.includes(permission))
  ) {
    return <ModulePermissionDenied permission={permission} />;
  }
  return <>{children}</>;
}
