"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Boxes,
  Bot,
  RotateCw,
  ShieldCheck,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { accessibleModules, useModuleAccess, type ModuleKey } from "@/lib/access/modules";
import { roleDisplayName } from "@/lib/api/identity-api";
import { useSession } from "@/lib/auth/session";

const modules: {
  href: string;
  accessKey: ModuleKey;
  kicker: string;
  title: string;
  tagline: string;
  capabilities: string[];
  icon: LucideIcon;
  accent: {
    tile: string;
    kicker: string;
    hoverBorder: string;
  };
  tour: string;
}[] = [
  {
    href: "/dashboard/agents",
    accessKey: "agents",
    kicker: "AI",
    title: "AI Agents",
    tagline:
      "Autonomous teammates that research, analyze, and draft — every action bound by the permissions you set.",
    capabilities: ["Delegate work", "Market scans", "Drafts & summaries"],
    icon: Bot,
    accent: {
      tile: "bg-violet-500/10 text-violet-600 ring-violet-500/20 dark:text-violet-400",
      kicker: "text-violet-600 dark:text-violet-400",
      hoverBorder: "hover:border-violet-500/40",
    },
    tour: "card-agents",
  },
  {
    href: "/dashboard/erp",
    accessKey: "erp",
    kicker: "ERP",
    title: "Business Operations",
    tagline:
      "Sales, inventory, finance, and HR on one source of truth — every department in sync, no silos.",
    capabilities: ["CRM", "Sales & orders", "Finance & HR"],
    icon: Boxes,
    accent: {
      tile: "bg-emerald-500/10 text-emerald-600 ring-emerald-500/20 dark:text-emerald-400",
      kicker: "text-emerald-600 dark:text-emerald-400",
      hoverBorder: "hover:border-emerald-500/40",
    },
    tour: "card-erp",
  },
  {
    href: "/dashboard/intelligence",
    accessKey: "intelligence",
    kicker: "Market",
    title: "Market Intelligence",
    tagline:
      "Search the market like you search the web — competitors, winning products, and trends from live signals.",
    capabilities: ["Competitors", "Trends", "Niches"],
    icon: Sparkles,
    accent: {
      tile: "bg-sky-500/10 text-sky-600 ring-sky-500/20 dark:text-sky-400",
      kicker: "text-sky-600 dark:text-sky-400",
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

  // A member who can reach exactly one module lands in it directly.
  useEffect(() => {
    if (status !== "ready" || available.length !== 1) return;
    router.replace(`/dashboard/${available[0]}`);
  }, [status, available, router]);

  const firstName = user?.fullName ? user.fullName.trim().split(/\s+/)[0] : "";
  const canInvite = permissions.includes("*") || permissions.includes("users:read");
  const canManageRoles = permissions.includes("*") || permissions.includes("roles:read");

  return (
    <div className="space-y-8">
      <section className={ENTER}>
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/25 to-primary/10 text-base font-semibold text-primary-foreground ring-1 ring-primary/20 ring-inset">
                {initialsFor(user?.fullName ?? "", user?.email ?? "")}
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-muted-foreground">
                  {user?.email ?? "Your workspace"}
                </p>
                <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
                  {greeting()}
                  {firstName ? `, ${firstName}` : ""}
                </h1>
              </div>
            </div>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
              Your workspace for Skyrict — invite your team, set roles and permissions, then open
              a space to start working.
            </p>
            {roles && roles.length > 0 ? (
              <div className="mt-4 flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Your access</span>
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

          <div className="flex flex-wrap items-center gap-2">
            {canInvite ? (
              <Button asChild>
                <Link href="/dashboard/members">
                  <UserPlus aria-hidden="true" className="size-4" />
                  Invite a member
                </Link>
              </Button>
            ) : null}
            {canManageRoles ? (
              <Button asChild variant="outline">
                <Link href="/dashboard/roles">
                  <ShieldCheck aria-hidden="true" className="size-4" />
                  Manage roles
                </Link>
              </Button>
            ) : null}
            <button
              type="button"
              onClick={replayTour}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <RotateCw aria-hidden="true" className="size-4" />
              Replay tour
            </button>
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className={ENTER} style={{ animationDelay: "80ms" }}>
          <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
            Your spaces
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {status === "ready" && available.length === 0
              ? "Your roles don't include any spaces yet. Ask an owner to update your access."
              : "Open a space to start working — each one runs entirely inside your roles and permissions."}
          </p>
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
                  className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-transparent via-current opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                />
                <div className="flex items-center gap-3">
                  <div
                    className={`flex size-11 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset ${module.accent.tile}`}
                  >
                    <module.icon aria-hidden="true" className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <p
                      className={`text-[11px] font-semibold tracking-wider uppercase ${module.accent.kicker}`}
                    >
                      {module.kicker}
                    </p>
                    <h3 className="font-display text-lg font-semibold tracking-tight text-foreground">
                      {module.title}
                    </h3>
                  </div>
                </div>

                <p className="mt-4 flex-1 text-sm leading-relaxed text-muted-foreground">
                  {module.tagline}
                </p>

                <ul className="mt-5 flex flex-wrap gap-1.5">
                  {module.capabilities.map((capability) => (
                    <li
                      key={capability}
                      className="rounded-full bg-muted/70 px-2.5 py-1 text-xs font-medium text-muted-foreground"
                    >
                      {capability}
                    </li>
                  ))}
                </ul>

                <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-foreground transition-colors group-hover:text-primary">
                  Open space
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
