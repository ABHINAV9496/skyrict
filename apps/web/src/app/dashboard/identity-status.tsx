"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ShieldCheck, UserRound } from "lucide-react";

import { ApiError } from "@/lib/api/http";
import {
  completeOnboarding,
  dismissOnboarding,
  getMyOrganization,
  getMyProfile,
  getMyRoles,
  type CurrentUserProfile,
  type MyRoles,
  type OrganizationProfile,
} from "@/lib/api/identity-api";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      roles: MyRoles;
      user: CurrentUserProfile;
      organization: OrganizationProfile;
      busy: "complete" | "dismiss" | null;
      actionError: string | null;
    };

function formatTimestamp(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
}

export default function IdentityStatusCard() {
  const [status, setStatus] = useState<Status>({ state: "loading" });

  async function load() {
    setStatus({ state: "loading" });
    try {
      const [roles, user, organization] = await Promise.all([
        getMyRoles(),
        getMyProfile(),
        getMyOrganization(),
      ]);
      setStatus({ state: "ready", roles, user, organization, busy: null, actionError: null });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load workspace status.";
      setStatus({ state: "error", message });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function run(action: "complete" | "dismiss") {
    if (status.state !== "ready") return;
    setStatus({ ...status, busy: action, actionError: null });
    try {
      if (action === "complete") {
        await completeOnboarding();
      } else {
        await dismissOnboarding();
      }
      await load();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "The action could not be completed.";
      setStatus((current) =>
        current.state === "ready"
          ? { ...current, busy: null, actionError: message }
          : { state: "error", message },
      );
    }
  }

  if (status.state === "loading") {
    return (
      <section className="rounded-xl border border-border bg-card p-4">
        <p className="text-sm text-muted-foreground">Loading workspace status…</p>
      </section>
    );
  }

  if (status.state === "error") {
    return (
      <section className="rounded-xl border border-border bg-card p-4">
        <p className="text-sm font-medium text-destructive">{status.message}</p>
      </section>
    );
  }

  const { roles, user, organization, busy, actionError } = status;
  const completedAt = formatTimestamp(organization.onboardingCompletedAt);
  const dismissedAt = formatTimestamp(user.onboardingDismissedAt);

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
        <h2 className="text-sm font-semibold text-foreground">Workspace status</h2>
      </div>

      {actionError ? (
        <p className="mt-2 text-sm font-medium text-destructive">{actionError}</p>
      ) : null}

      <div className="mt-3 space-y-2 text-sm">
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Roles:</span>{" "}
          {roles.roles.length ? roles.roles.join(", ") : "None"}
        </p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Permissions:</span>{" "}
          {roles.permissions.length} granted
        </p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Organization onboarding:</span>{" "}
          {completedAt ? (
            <span className="inline-flex items-center gap-1 text-emerald-600">
              <CheckCircle2 aria-hidden="true" className="size-4" />
              Completed {completedAt}
            </span>
          ) : (
            "Pending"
          )}
        </p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Onboarding reminders:</span>{" "}
          {dismissedAt ? `Dismissed ${dismissedAt}` : "Active"}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={Boolean(completedAt) || busy !== null}
          onClick={() => void run("complete")}
          className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === "complete" ? "Completing…" : "Complete onboarding"}
        </button>
        <button
          type="button"
          disabled={Boolean(dismissedAt) || busy !== null}
          onClick={() => void run("dismiss")}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <UserRound aria-hidden="true" className="size-3.5" />
          {busy === "dismiss" ? "Dismissing…" : "Dismiss onboarding"}
        </button>
      </div>
    </section>
  );
}
