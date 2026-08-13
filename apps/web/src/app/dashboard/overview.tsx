"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Boxes,
  RotateCw,
  ShieldCheck,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { getMyRoles, roleDisplayName } from "@/lib/api/identity-api";
import { useSession } from "@/lib/auth/session";

const modules: {
  href: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tour: string;
}[] = [
  {
    href: "/dashboard/agents",
    title: "AI Agents",
    description:
      "Autonomous agents that act on the tasks you hand them, within the permissions you set.",
    icon: Bot,
    tour: "card-agents",
  },
  {
    href: "/dashboard/erp",
    title: "ERP",
    description:
      "CRM, sales, inventory, finance, and HR on the same data — nothing out of sync.",
    icon: Boxes,
    tour: "card-erp",
  },
  {
    href: "/dashboard/intelligence",
    title: "Intelligence",
    description:
      "External signals and market trends, so decisions are backed by data rather than guesses.",
    icon: Sparkles,
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
  const [roles, setRoles] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMyRoles()
      .then((data) => {
        if (!cancelled) setRoles(data.roles);
      })
      .catch(() => {
        if (!cancelled) setRoles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const firstName = user?.fullName ? user.fullName.trim().split(/\s+/)[0] : "";

  return (
    <div className="space-y-8">
      <section className={ENTER}>
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-sm font-semibold text-primary-foreground">
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
              Your launchpad for Skyrict — invite your team, shape roles and permissions, then open
              a module to start working.
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
            <Button asChild>
              <Link href="/dashboard/members">
                <UserPlus aria-hidden="true" className="size-4" />
                Invite a member
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/dashboard/roles">
                <ShieldCheck aria-hidden="true" className="size-4" />
                Manage roles
              </Link>
            </Button>
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
            Launchpad
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">Open a module and start working.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          {modules.map((module, index) => (
            <Link
              key={module.href}
              href={module.href}
              data-tour={module.tour}
              style={{ animationDelay: `${120 + index * 80}ms` }}
              className={`group relative flex flex-col rounded-xl border border-border bg-card p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-muted/40 active:translate-y-0 ${ENTER}`}
            >
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
                <module.icon aria-hidden="true" className="size-5" />
              </div>
              <h3 className="mt-4 font-display text-base font-semibold text-foreground">
                {module.title}
              </h3>
              <p className="mt-1 flex-1 text-sm leading-relaxed text-muted-foreground">
                {module.description}
              </p>
              <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                Open module
                <ArrowRight
                  aria-hidden="true"
                  className="size-4 transition-transform duration-200 group-hover:translate-x-0.5"
                />
              </span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
