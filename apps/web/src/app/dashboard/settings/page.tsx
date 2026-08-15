"use client";

import { useRef, useState } from "react";
import { LogOut, Plug, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { SettingsSkeleton } from "@/components/ui/page-skeletons";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AuthUser } from "@/lib/api/auth-api";
import { removeAvatar, uploadAvatar } from "@/lib/api/auth-api";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

function initialsFor(name: string, email: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase() || "SK";
}

/** Same-origin avatar URL served by /api/auth/avatar/{user_id}/{filename}. */
function avatarSrc(user: AuthUser | null): string | null {
  return user?.avatarUrl ? `/api/auth/avatar/${user.avatarUrl}` : null;
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
  const { user, status, updateUser, logout } = useSession();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [confirmLogout, setConfirmLogout] = useState(false);

  const src = avatarSrc(user);

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setAvatarError(null);
    setAvatarBusy(true);
    try {
      updateUser(await uploadAvatar(file));
    } catch (error) {
      setAvatarError(error instanceof Error ? error.message : "Could not update your avatar.");
    } finally {
      setAvatarBusy(false);
    }
  }

  async function handleRemoveAvatar() {
    setAvatarError(null);
    setAvatarBusy(true);
    try {
      updateUser(await removeAvatar());
    } catch (error) {
      setAvatarError(error instanceof Error ? error.message : "Could not remove your avatar.");
    } finally {
      setAvatarBusy(false);
    }
  }

  if (status === "loading") return <SettingsSkeleton />;

  return (
    <div className="space-y-6 pb-8">
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
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <div className="relative size-16 shrink-0">
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt={user?.fullName ? `${user.fullName}'s avatar` : "Profile avatar"}
                className="size-16 rounded-full object-cover ring-1 ring-border"
              />
            ) : (
              <div className="flex size-16 items-center justify-center rounded-full bg-primary/15 text-xl font-semibold text-primary-foreground">
                {initialsFor(user?.fullName ?? "", user?.email ?? "")}
              </div>
            )}
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={avatarBusy}
                className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted/60 disabled:opacity-50"
              >
                {avatarBusy ? "Uploading…" : "Upload photo"}
              </button>
              {src && (
                <button
                  type="button"
                  onClick={() => void handleRemoveAvatar()}
                  disabled={avatarBusy}
                  className="rounded-lg px-3 py-1.5 text-sm font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Square image. Resized and optimized automatically.
            </p>
            {avatarError && <p className="text-xs text-destructive">{avatarError}</p>}
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          aria-label="Choose an avatar image"
          className="hidden"
          onChange={(event) => void handleFileChange(event)}
        />
        <div className="mt-4 flex items-center gap-3 border-t border-border pt-4">
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
        onClick={() => setConfirmLogout(true)}
        disabled={status !== "authenticated"}
        className="flex items-center gap-2 rounded-lg border border-destructive/30 px-3 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
      >
        <LogOut aria-hidden="true" className="size-4" />
        Sign out
      </button>

      <Dialog open={confirmLogout} onOpenChange={setConfirmLogout}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Sign out?</DialogTitle>
            <DialogDescription>
              You&apos;ll need to sign in again to access your workspace.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmLogout(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirmLogout(false);
                void logout();
              }}
            >
              Sign out
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
