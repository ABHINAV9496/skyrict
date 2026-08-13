"use client";

import { useEffect, useMemo, type ComponentType } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Blocks,
  Radar,
  RotateCw,
  ShieldCheck,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import { AiGlyph } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { OverviewSkeleton } from "@/components/ui/page-skeletons";
import { accessibleModules, useModuleAccess, type ModuleKey } from "@/lib/access/modules";
import { roleDisplayName } from "@/lib/api/identity-api";
import { useSession } from "@/lib/auth/session";

type ModuleIcon = LucideIcon | ComponentType<{ className?: string }>;

const modules: {
  href: string;
  accessKey: ModuleKey;
  title: string;
  oneLine: string;
  icon: ModuleIcon;
  accent: {
    tile: string;
    topBar: string;
    hoverBorder: string;
  };
  tour: string;
}[] = [
  {
    href: "/dashboard/agents",
    accessKey: "agents",
    title: "AI Agents",
    oneLine: "Delegate tasks to your AI team.",
    icon: AiGlyph,
    accent: {
      tile: "bg-gradient-to-br from-violet-500/20 to-violet-500/5 text-violet-600 ring-violet-500/20 dark:text-violet-400",
      topBar: "bg-violet-500/60",
      hoverBorder: "hover:border-violet-500/40",
    },
    tour: "card-agents",
  },
  {
    href: "/dashboard/erp",
    accessKey: "erp",
    title: "Business Operations",
    oneLine: "Every department, one source of truth.",
    icon: Blocks,
    accent: {
      tile: "bg-gradient-to-br from-emerald-500/20 to-emerald-500/5 text-emerald-600 ring-emerald-500/20 dark:text-emerald-400",
      topBar: "bg-emerald-500/60",
      hoverBorder: "hover:border-emerald-500/40",
    },
    tour: "card-erp",
  },
  {
    href: "/dashboard/intelligence",
    accessKey: "intelligence",
    title: "Market Intelligence",
    oneLine: "Competitors, trends, and niches.",
    icon: Radar,
    accent: {
      tile: "bg-gradient-to-br from-sky-500/20 to-sky-500/5 text-sky-600 ring-sky-500/20 dark:text-sky-400",
      topBar: "bg-sky-500/60",
      hoverBorder: "hover:border-sky-500/40",
    },
    tour: "card-intelligence",
  },
];

const ENTER =
  "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-3 motion-safe:duration-500 motion-safe:fill-mode-backwards";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function initialsFor(name: string, email: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase() || "SK";
}

function replayTour() {
  window.dispatchEvent(new Event("skyrict:start-tour"));
}

export default function OverviewClient() {
  const { user } = useSession();
  const router = useRouter();
  const { status, access, roles, permissions } = useModuleAccess();

  const available = useMemo(() => accessibleModules(access), [access]);
  const visibleModules = useMemo(
    () => modules.filter((module) => access[module.accessKey]),
    [access],
  );

  // A member who can reach exactly one space lands in it directly.
  useEffect(() => {
    if (status !== "ready" || available.length !== 1) return;
    router.replace(`/dashboard/${available[0]}`);
  }, [status, available, router]);

  const firstName = user?.fullName ? user.fullName.trim().split(/\s+/)[0] : "";
  const canInvite = permissions.includes("*") || permissions.includes("users:read");
  const canManageRoles = permissions.includes("*") || permissions.includes("roles:read");

  if (status === "loading") return <OverviewSkeleton />;

  return (
    <div className="space-y-8">
      <section className={`overflow-hidden rounded-2xl border border-border bg-card ${ENTER}`}>
        <div className="relative p-6 sm:p-8">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent"
          />
          <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/25 to-primary/10 text-base font-semibold text-primary-foreground ring-1 ring-primary/20 ring-inset">
                {initialsFor(user?.fullName ?? "", user?.email ?? "")}
              </div>
              <div className="min-w-0">
                <h1 className="truncate font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
                  {greeting()}
                  {firstName ? `, ${firstName}` : ""}
                </h1>
                {roles && roles.length > 0 ? (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {roles.map((role) => (
                      <span
                        key={role}
                        className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                      >
                        {roleDisplayName(role)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {canInvite ? (
                <Button asChild>
                  <Link href="/dashboard/invite">
                    <UserPlus aria-hidden="true" className="size-4" />
                    Invite
                  </Link>
                </Button>
              ) : null}
              {canManageRoles ? (
                <Button asChild variant="outline">
                  <Link href="/dashboard/roles">
                    <ShieldCheck aria-hidden="true" className="size-4" />
                    Roles
                  </Link>
                </Button>
              ) : null}
              <button
                type="button"
                onClick={replayTour}
                title="Replay tour"
                aria-label="Replay tour"
                className="flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <RotateCw aria-hidden="true" className="size-4" />
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-5">
        <div className={ENTER} style={{ animationDelay: "80ms" }}>
          <div className="flex items-center gap-3">
            <h2 className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
              Spaces
            </h2>
            <div aria-hidden="true" className="h-px flex-1 bg-border" />
          </div>
        </div>

        {visibleModules.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-3">
            {visibleModules.map((module, index) => (
              <Link
                key={module.href}
                href={module.href}
                data-tour={module.tour}
                style={{ animationDelay: `${120 + index * 80}ms` }}
                className={`group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card p-6 transition-all duration-200 hover:-translate-y-1 hover:shadow-lg hover:shadow-primary/5 active:translate-y-0 ${module.accent.hoverBorder} ${ENTER}`}
              >
                <span
                  aria-hidden="true"
                  className={`absolute inset-x-0 top-0 h-0.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100 ${module.accent.topBar}`}
                />
                <div
                  className={`flex size-12 shrink-0 items-center justify-center rounded-2xl ring-1 ring-inset ${module.accent.tile}`}
                >
                  <module.icon aria-hidden="true" className="size-6" />
                </div>
                <h3 className="mt-5 font-display text-lg font-semibold tracking-tight text-foreground">
                  {module.title}
                </h3>
                <p className="mt-1.5 flex-1 text-sm leading-relaxed text-muted-foreground">
                  {module.oneLine}
                </p>
                <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-foreground transition-colors group-hover:text-primary">
                  Open
                  <ArrowRight
                    aria-hidden="true"
                    className="size-4 transition-transform duration-200 group-hover:translate-x-0.5"
                  />
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-card/60 p-10 text-center">
            <p className="text-sm text-muted-foreground">
              No spaces available yet. Contact a workspace owner to grant you access.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
