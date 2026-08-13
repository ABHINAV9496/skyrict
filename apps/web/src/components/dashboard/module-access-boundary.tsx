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

export function ModuleLoading() {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-border/70 bg-card/85 px-4 lg:px-6">
        <div className="h-5 w-36 animate-pulse rounded-md bg-muted" />
        <div className="h-9 w-9 animate-pulse rounded-lg bg-muted" />
      </div>
      <div className="mx-auto w-full max-w-4xl flex-1 space-y-6 px-4 py-12 lg:px-6">
        <div className="flex items-center gap-3">
          <div className="size-10 animate-pulse rounded-xl bg-muted" />
          <div className="space-y-2">
            <div className="h-5 w-44 animate-pulse rounded-md bg-muted" />
            <div className="h-3 w-64 animate-pulse rounded-md bg-muted" />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-36 animate-pulse rounded-xl border border-border bg-card" />
          ))}
        </div>
      </div>
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
 */
export function ModuleAccessBoundary({
  module,
  children,
}: {
  module: ModuleKey;
  children: React.ReactNode;
}) {
  const { status, access } = useModuleAccess();

  if (status === "loading") return <ModuleLoading />;
  if (status === "error") return <ModuleAccessError module={module} />;
  if (!access[module]) return <ModuleAccessDenied module={module} />;
  return <>{children}</>;
}
