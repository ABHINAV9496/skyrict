"use client";

import { LogOut, Plug, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { SettingsSkeleton } from "@/components/ui/page-skeletons";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

function initialsFor(name: string, email: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase() || "SK";
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

function StatusBadge({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-xs font-medium",
        enabled
          ? "bg-emerald-500/10 text-emerald-600"
          : "bg-muted text-muted-foreground",
      )}
    >
      {enabled ? "Enabled" : "Disabled"}
    </span>
  );
}

export default function SettingsPage() {
  const { user, status, logout } = useSession();

  if (status === "loading") return <SettingsSkeleton />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Manage your profile, security, and workspace preferences."
        icon={SlidersHorizontal}
      />

      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <UserRound aria-hidden="true" className="size-5 text-primary" />
          Profile
        </h2>
        <div className="mt-3 flex items-center gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary-foreground">
            {initialsFor(user?.fullName ?? "", user?.email ?? "")}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">
              {user?.fullName || "—"}
            </p>
            <p className="truncate text-sm text-muted-foreground">{user?.email}</p>
          </div>
        </div>
        <dl className="mt-3 divide-y divide-border">
          <DetailRow label="Email" value={user?.email ?? "—"} />
          <DetailRow
            label="Member since"
            value={
              user?.createdAt ? new Date(user.createdAt).toLocaleDateString() : "—"
            }
          />
        </dl>
      </section>

      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
          Security
        </h2>
        <dl className="mt-3 divide-y divide-border">
          <DetailRow
            label="Two-factor authentication"
            value={<StatusBadge enabled={Boolean(user?.mfaEnabled)} />}
          />
          <DetailRow
            label="Email verified"
            value={
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-xs font-medium",
                  user?.isVerified
                    ? "bg-emerald-500/10 text-emerald-600"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {user?.isVerified ? "Verified" : "Unverified"}
              </span>
            }
          />
        </dl>
      </section>

      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Plug aria-hidden="true" className="size-5 text-primary" />
          Integrations
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Billing and third-party integrations are on the way — check back soon.
        </p>
      </section>

      <button
        type="button"
        onClick={() => void logout()}
        disabled={status !== "authenticated"}
        className="flex items-center gap-2 rounded-lg border border-destructive/30 px-3 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
      >
        <LogOut aria-hidden="true" className="size-4" />
        Sign out
      </button>
    </div>
  );
}
