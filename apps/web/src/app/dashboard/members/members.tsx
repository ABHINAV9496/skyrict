"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Mail, UserPlus } from "lucide-react";

import { ApiError } from "@/lib/api/http";
import {
  createInvitation,
  expireInvitation,
  listInvitations,
  listRoles,
  type InvitationCreated,
  type InvitationSummary,
  type RoleSummary,
} from "@/lib/api/identity-api";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      invitations: InvitationSummary[];
      roles: RoleSummary[];
      busy: string | null;
    };

function invitationState(item: InvitationSummary): "used" | "expired" | "pending" {
  if (item.usedAt) return "used";
  if (item.expiresAt && new Date(item.expiresAt).getTime() < Date.now()) return "expired";
  return "pending";
}

function statusLabel(item: InvitationSummary): string {
  switch (invitationState(item)) {
    case "used":
      return "Used";
    case "expired":
      return "Expired";
    default:
      return "Pending";
  }
}

/** `{slug}.signin.{apex}/invite?token=...` link for a freshly created invite. */
function inviteLink(token: string): string {
  const hostname = window.location.hostname;
  const parts = hostname.split(".");
  const signinHost = `${parts[0]}.signin.${parts.slice(1).join(".")}`;
  const port = window.location.port ? `:${window.location.port}` : "";
  return `${window.location.protocol}//${signinHost}${port}/invite?token=${encodeURIComponent(token)}`;
}

export default function MembersClient() {
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [email, setEmail] = useState("");
  const [roleName, setRoleName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [created, setCreated] = useState<InvitationCreated | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [invitations, roles] = await Promise.all([listInvitations(), listRoles()]);
      setStatus({ state: "ready", invitations, roles, busy: null });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load members.";
      setStatus({ state: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const defaultRole = useMemo(
    () => (status.state === "ready" && status.roles.length > 0 ? status.roles[0].name : ""),
    [status],
  );

  useEffect(() => {
    setRoleName((current) => current || defaultRole);
  }, [defaultRole]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setCreated(null);
    try {
      const result = await createInvitation(email, roleName);
      setEmail("");
      setCreated(result);
      await load();
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "The invitation could not be sent.");
    }
  }

  async function onExpire(invitationId: string) {
    if (status.state !== "ready") return;
    setStatus({ ...status, busy: invitationId });
    setActionError(null);
    try {
      await expireInvitation(invitationId);
      await load();
    } catch (error) {
      setActionError(
        error instanceof ApiError ? error.message : "The invitation could not be expired.",
      );
      setStatus((current) => (current.state === "ready" ? { ...current, busy: null } : current));
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-display text-2xl font-semibold text-foreground">Members</h1>
        <p className="text-sm text-muted-foreground">
          Invite teammates to your workspace. Invites expire and can be revoked.
        </p>
      </div>

      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <UserPlus aria-hidden="true" className="size-5 text-primary" />
          Invite a member
        </h2>
        <form onSubmit={(event) => void onSubmit(event)} className="mt-3 flex flex-wrap gap-2">
          <label className="sr-only" htmlFor="invite-email">
            Email address
          </label>
          <input
            id="invite-email"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="teammate@example.com"
            className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
          />
          <label className="sr-only" htmlFor="invite-role">
            Role
          </label>
          <select
            id="invite-role"
            value={roleName}
            onChange={(event) => setRoleName(event.target.value)}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
          >
            {status.state === "ready" && status.roles.length > 0 ? (
              status.roles.map((role) => (
                <option key={role.id} value={role.name}>
                  {role.name}
                </option>
              ))
            ) : (
              <option value="standard_user">standard_user</option>
            )}
          </select>
          <button
            type="submit"
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Send invite
          </button>
        </form>
        {formError ? (
          <p className="mt-2 text-sm font-medium text-destructive">{formError}</p>
        ) : null}
        {created ? (
          <div className="mt-3 space-y-1 rounded-lg border border-primary/30 bg-muted/40 p-3 text-sm">
            <p className="font-medium text-foreground">
              Invitation sent to {created.email} as {created.roleName}
            </p>
            <p className="break-all text-muted-foreground">
              <span className="font-medium text-foreground">Invite link</span>{" "}
              <a
                href={inviteLink(created.token)}
                className="text-primary underline decoration-primary/40 underline-offset-2"
              >
                {inviteLink(created.token)}
              </a>
            </p>
            <p className="text-xs text-muted-foreground">
              Token (shown once): <code className="break-all">{created.token}</code>
            </p>
          </div>
        ) : null}
      </section>

      {status.state === "loading" ? (
        <p className="text-sm text-muted-foreground">Loading members…</p>
      ) : null}
      {status.state === "error" ? (
        <p className="text-sm font-medium text-destructive">{status.message}</p>
      ) : null}
      {status.state === "ready" ? (
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Mail aria-hidden="true" className="size-5 text-primary" />
            Invitations
          </h2>
          {status.invitations.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">No invitations yet.</p>
          ) : (
            <>
              {actionError ? (
                <p className="mt-2 text-sm font-medium text-destructive">{actionError}</p>
              ) : null}
              <ul className="mt-3 divide-y divide-border">
              {status.invitations.map((item) => {
                const state = invitationState(item);
                return (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-2 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{item.email}</p>
                      <p className="text-xs text-muted-foreground">
                        {item.roleName} · created {new Date(item.createdAt).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          state === "used"
                            ? "bg-emerald-500/10 text-emerald-600"
                            : state === "expired"
                              ? "bg-muted text-muted-foreground"
                              : "bg-primary/10 text-primary"
                        }`}
                      >
                        {statusLabel(item)}
                      </span>
                      {state === "pending" ? (
                        <button
                          type="button"
                          disabled={status.busy !== null}
                          onClick={() => void onExpire(item.id)}
                          className="rounded-lg border border-border px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted/40 disabled:opacity-50"
                        >
                          Expire
                        </button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
              </ul>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
