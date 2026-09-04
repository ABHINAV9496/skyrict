"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Monitor, ShieldCheck, Smartphone, Tablet, Trash2, Users } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useModuleAccess } from "@/lib/access/modules";
import { ApiError } from "@/lib/api/http";
import {
  listMemberSessions,
  listMembers,
  listRoles,
  removeMember,
  revokeAllMemberSessions,
  revokeMemberSession,
  roleBadgeClass,
  roleDisplayName,
  updateMemberRole,
  type Member,
  type RoleSummary,
  type SessionInfo,
} from "@/lib/api/identity-api";
import { ListSkeleton } from "@/components/ui/page-skeletons";
import { cn } from "@/lib/utils";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      members: Member[];
      roles: RoleSummary[];
      busy: string | null;
    };

function formatJoinedAt(value: string | null): string {
  if (!value) return "recently";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "recently";
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function memberInitials(member: Member): string {
  const parts = member.fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1) {
    return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
  }
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return member.email.slice(0, 2).toUpperCase() || "SK";
}

function relativeTime(value: string): string {
  const elapsed = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (!Number.isFinite(elapsed) || elapsed < 60) return "just now";
  const minutes = Math.round(elapsed / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function DeviceIcon({ deviceType }: { deviceType: string | null }) {
  const type = deviceType?.toLowerCase() ?? "";
  if (type.includes("mobile") || type.includes("phone")) {
    return <Smartphone aria-hidden="true" className="size-4 text-primary" />;
  }
  if (type.includes("tablet")) {
    return <Tablet aria-hidden="true" className="size-4 text-primary" />;
  }
  return <Monitor aria-hidden="true" className="size-4 text-primary" />;
}

const GENERIC_PLATFORM_FAMILIES = new Set(["Windows PC", "Linux PC", "Android Desktop", "Desktop"]);

function sessionTitle(session: SessionInfo): string {
  if (session.deviceType === "service") {
    return `${session.deviceFamily ?? "API client"} · API client`;
  }
  const browser = [session.browserName, session.browserVersion].filter(Boolean).join(" ");
  if (browser) {
    return session.osName ? `${browser} · ${session.osName}` : browser;
  }
  const familyAndOs = [session.deviceFamily, session.osName].filter(Boolean).join(" · ");
  if (familyAndOs) return familyAndOs;
  return session.device || "Unknown device";
}

function sessionDetail(session: SessionInfo): string {
  const parts: string[] = [];
  if (session.deviceType !== "service" && session.deviceFamily) {
    if (!GENERIC_PLATFORM_FAMILIES.has(session.deviceFamily)) {
      parts.push(session.deviceFamily);
    }
  }
  if (session.ipAddress) parts.push(session.ipAddress);
  return parts.join(" · ");
}

function SkeletonRows() {
  return <ListSkeleton rows={3} />;
}

export default function MembersClient() {
  const access = useModuleAccess();
  const { status: accessStatus, permissions } = access;

  const canChangeRoles =
    permissions.includes("*") ||
    (permissions.includes("users:write") && permissions.includes("roles:read"));
  const canRemove = permissions.includes("*") || permissions.includes("users:delete");
  const canViewSessions =
    permissions.includes("*") || permissions.includes("sessions:read");
  const canRevokeSessions =
    permissions.includes("*") || permissions.includes("sessions:revoke");

  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);

  const [pendingRemove, setPendingRemove] = useState<Member | null>(null);
  const [removing, setRemoving] = useState(false);

  const [sessionsFor, setSessionsFor] = useState<Member | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [sessionsStatus, setSessionsStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [sessionBusy, setSessionBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const members = await listMembers();
      let roles: RoleSummary[] = [];
      if (canChangeRoles) {
        try {
          roles = await listRoles();
        } catch {
          // Roles are optional here: without them the UI falls back to static
          // role badges instead of the editable dropdown.
        }
      }
      setStatus({ state: "ready", members, roles, busy: null });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load members.";
      setStatus({ state: "error", message });
    }
  }, [canChangeRoles]);

  useEffect(() => {
    if (accessStatus !== "loading") void load();
  }, [accessStatus, load]);

  async function onChangeRole(memberId: string, role: string) {
    if (status.state !== "ready") return;
    setStatus({ ...status, busy: memberId });
    setActionError(null);
    try {
      await updateMemberRole(memberId, role);
      await load();
    } catch (error) {
      setActionError(
        error instanceof ApiError ? error.message : "Could not update the member's role.",
      );
      setStatus((current) => (current.state === "ready" ? { ...current, busy: null } : current));
    }
  }

  async function onRemove() {
    if (!pendingRemove || status.state !== "ready") return;
    setRemoving(true);
    setActionError(null);
    try {
      await removeMember(pendingRemove.id);
      setPendingRemove(null);
      await load();
    } catch (error) {
      setActionError(
        error instanceof ApiError ? error.message : "Could not remove the member.",
      );
    } finally {
      setRemoving(false);
    }
  }

  async function openSessions(member: Member) {
    setSessionsFor(member);
    setSessions(null);
    setSessionsStatus("loading");
    setSessionsError(null);
    setSessionBusy(null);
    try {
      const list = await listMemberSessions(member.id);
      setSessions(list);
      setSessionsStatus("ready");
    } catch (error) {
      setSessionsStatus("error");
      setSessionsError(
        error instanceof ApiError ? error.message : "Could not load this member's sessions.",
      );
    }
  }

  function closeSessions() {
    if (sessionBusy !== null) return;
    setSessionsFor(null);
    setSessions(null);
  }

  async function onRevokeSession(sessionId: string) {
    if (!sessionsFor) return;
    setSessionBusy(sessionId);
    setSessionsError(null);
    try {
      await revokeMemberSession(sessionsFor.id, sessionId);
      setSessions((current) => (current ?? []).filter((session) => session.id !== sessionId));
    } catch (error) {
      setSessionsError(
        error instanceof ApiError ? error.message : "Could not log out that device.",
      );
    } finally {
      setSessionBusy(null);
    }
  }

  async function onRevokeAllSessions() {
    if (!sessionsFor) return;
    setSessionBusy("__all__");
    setSessionsError(null);
    try {
      await revokeAllMemberSessions(sessionsFor.id);
      setSessions([]);
    } catch (error) {
      setSessionsError(
        error instanceof ApiError
          ? error.message
          : "Could not log the member out of all devices.",
      );
    } finally {
      setSessionBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Members"
        description="Manage who has access to this workspace roles, devices, and access."
        icon={Users}
      />

      {actionError ? (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
          {actionError}
        </p>
      ) : null}

      <section className="rounded-xl border border-border bg-card">
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
          <h2 className="flex items-center gap-2 font-display text-sm font-semibold text-foreground">
            <Users aria-hidden="true" className="size-4 text-primary" />
            All members
          </h2>
          {status.state === "ready" ? (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">
              {status.members.length}
            </span>
          ) : null}
        </header>

        <div className="p-5">
          {status.state === "loading" ? <SkeletonRows /> : null}

          {status.state === "error" ? (
            <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
              <p className="text-sm font-medium text-destructive">{status.message}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => void load()}
              >
                Try again
              </Button>
            </div>
          ) : null}

          {status.state === "ready" && status.members.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
              <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Users aria-hidden="true" className="size-5" />
              </div>
              <h3 className="mt-3 font-display text-sm font-semibold text-foreground">
                No members yet
              </h3>
              <p className="mt-1 max-w-60 text-xs leading-relaxed text-muted-foreground">
                Invite your first teammate to start collaborating in this workspace.
              </p>
            </div>
          ) : null}

          {status.state === "ready" && status.members.length > 0 ? (
            <ul className="divide-y divide-border">
              {status.members.map((member) => {
                const busy = status.busy === member.id;
                const isSelf = member.isSelf;
                const isOwner = member.roleName === "tenant_owner";
                const knownRole = status.roles.some(
                  (role) => role.name === member.roleName,
                );
                return (
                  <li
                    key={member.id}
                    className="flex items-center gap-3 py-3.5 transition-colors first:pt-0 last:pb-0"
                  >
                    {member.avatarUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={`/api/auth/avatar/${member.avatarUrl}`}
                        alt=""
                        className="size-9 shrink-0 rounded-lg object-cover ring-1 ring-border"
                      />
                    ) : (
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-semibold text-primary">
                        {memberInitials(member)}
                      </div>
                    )}

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium text-foreground">
                          {member.fullName || member.email}
                        </p>
                        {isSelf ? (
                          <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                            You
                          </span>
                        ) : null}
                        {busy ? (
                          <LoaderCircle
                            aria-hidden="true"
                            className="size-3.5 shrink-0 animate-spin text-muted-foreground"
                          />
                        ) : null}
                      </div>
                      <p className="truncate text-xs text-muted-foreground">
                        {member.email} · joined {formatJoinedAt(member.joinedAt)}
                      </p>
                    </div>

                    <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                      {canChangeRoles && !isSelf && !isOwner && knownRole ? (
                        <Select
                          value={member.roleName}
                          onValueChange={(value) => {
                            if (value !== member.roleName) {
                              void onChangeRole(member.id, value);
                            }
                          }}
                          disabled={status.busy !== null}
                        >
                          <SelectTrigger
                            size="sm"
                            className={cn(
                              "gap-1.5",
                              roleBadgeClass(member.roleName),
                            )}
                            aria-label={`Change role for ${member.fullName || member.email}`}
                          >
                            <ShieldCheck aria-hidden="true" className="size-3.5" />
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {status.roles.map((role) => (
                              <SelectItem key={role.id} value={role.name}>
                                {roleDisplayName(role.name)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                            roleBadgeClass(member.roleName),
                          )}
                        >
                          <ShieldCheck aria-hidden="true" className="size-3" />
                          {roleDisplayName(member.roleName) || "Member"}
                        </span>
                      )}

                      {canViewSessions ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={status.busy !== null}
                          onClick={() => void openSessions(member)}
                        >
                          <Monitor aria-hidden="true" className="size-3.5" />
                          Sessions
                        </Button>
                      ) : null}

                      {canRemove && !isSelf && !isOwner ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                          disabled={status.busy !== null}
                          onClick={() => setPendingRemove(member)}
                        >
                          <Trash2 aria-hidden="true" className="size-3.5" />
                          Remove
                        </Button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      </section>

      <Dialog
        open={pendingRemove !== null}
        onOpenChange={(open) => {
          if (!open && !removing) setPendingRemove(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove member?</DialogTitle>
            <DialogDescription>
              {pendingRemove
                ? `${pendingRemove.fullName || pendingRemove.email} will immediately lose access to this workspace. This cannot be undone.`
                : "This member will immediately lose access to this workspace. This cannot be undone."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPendingRemove(null)}
              disabled={removing}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void onRemove()}
              disabled={removing}
            >
              {removing ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Remove member
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={sessionsFor !== null}
        onOpenChange={(open) => {
          if (!open) closeSessions();
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Active sessions</DialogTitle>
            <DialogDescription>
              {sessionsFor
                ? `Devices ${sessionsFor.fullName || sessionsFor.email} is signed in on in this workspace.`
                : "Devices this member is signed in on in this workspace."}
            </DialogDescription>
          </DialogHeader>

          {sessionsStatus === "loading" ? <ListSkeleton rows={2} /> : null}

          {sessionsStatus === "error" ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {sessionsError}
            </p>
          ) : null}

          {sessionsStatus === "ready" && (sessions ?? []).length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-8 text-center">
              <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <ShieldCheck aria-hidden="true" className="size-5" />
              </div>
              <h3 className="mt-3 font-display text-sm font-semibold text-foreground">
                No active sessions
              </h3>
              <p className="mt-1 max-w-64 text-xs leading-relaxed text-muted-foreground">
                {sessionsFor?.isSelf
                  ? "You are not signed in on any device in this workspace right now."
                  : "This member is not signed in on any device in this workspace right now."}
              </p>
            </div>
          ) : null}

          {sessionsStatus === "ready" && (sessions ?? []).length > 0 ? (
            <div className="space-y-2">
              {sessionsError ? (
                <p role="alert" className="text-sm font-medium text-destructive">
                  {sessionsError}
                </p>
              ) : null}
              <ul className="divide-y divide-border rounded-lg border border-border">
                {(sessions ?? []).map((session) => {
                  const busy = sessionBusy === session.id;
                  const detail = sessionDetail(session);
                  return (
                    <li
                      key={session.id}
                      className="flex items-center gap-3 px-3 py-2.5 first:rounded-t-lg last:rounded-b-lg"
                    >
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <DeviceIcon deviceType={session.deviceType} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="truncate text-sm font-medium text-foreground">
                            {sessionTitle(session)}
                          </p>
                          {session.isTrusted ? (
                            <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                              Trusted
                            </span>
                          ) : null}
                        </div>
                        <p className="truncate text-xs text-muted-foreground">
                          {detail ? `${detail} · ` : ""}active {relativeTime(session.lastActiveAt)}
                        </p>
                      </div>
                      {canRevokeSessions && !sessionsFor?.isSelf ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={sessionBusy !== null}
                          onClick={() => void onRevokeSession(session.id)}
                        >
                          {busy ? (
                            <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
                          ) : null}
                          Log out
                        </Button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          <DialogFooter showCloseButton>
            {canRevokeSessions && !sessionsFor?.isSelf ? (
              <Button
                type="button"
                variant="destructive"
                disabled={sessionBusy !== null}
                onClick={() => void onRevokeAllSessions()}
              >
                {sessionBusy === "__all__" ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : null}
                Log out all devices
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
