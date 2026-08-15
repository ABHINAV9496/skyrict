"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, SlidersHorizontal } from "lucide-react";

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

/**
 * Sidebar user menu. The avatar + name row is the trigger; clicking it opens a
 * menu with Profile settings and Sign out, so the logout action no longer sits
 * directly in the footer.
 */
export function UserMenu({ collapsed = false }: { collapsed?: boolean }) {
  const { user, logout } = useSession();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const lastPathname = useRef(pathname);

  useEffect(() => {
    if (lastPathname.current !== pathname) {
      lastPathname.current = pathname;
      setOpen(false);
    }
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const src = avatarSrc(user);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={collapsed ? user?.fullName || user?.email || "Account" : undefined}
        className={cn(
          "flex w-full items-center gap-3 rounded-lg text-left transition-colors hover:bg-muted/60",
          collapsed ? "justify-center px-2 py-1" : "px-2 py-1.5",
        )}
      >
        <span className="flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/15 text-[11px] font-semibold text-primary-foreground">
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={src}
              alt={user?.fullName ? `${user.fullName}'s avatar` : "Profile avatar"}
              className="size-full object-cover"
            />
          ) : (
            initialsFor(user?.fullName ?? "", user?.email ?? "")
          )}
        </span>
        {!collapsed ? (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-foreground">
                {user?.fullName || user?.email || "Account"}
              </span>
              <span className="block truncate text-[11px] text-muted-foreground">
                {user?.email}
              </span>
            </span>
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "size-3.5 shrink-0 text-muted-foreground transition-transform",
                open && "rotate-180",
              )}
            />
          </>
        ) : null}
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="User menu"
          className={cn(
            "absolute bottom-full z-50 mb-1 min-w-44 rounded-lg border border-border bg-card p-1 shadow-lg",
            collapsed ? "left-1/2 -translate-x-1/2" : "left-0 right-0",
          )}
        >
          <Link
            role="menuitem"
            href="/dashboard/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
          >
            <SlidersHorizontal aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
            Profile settings
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              setConfirmOpen(true);
            }}
            className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/10"
          >
            <LogOut aria-hidden="true" className="size-4 shrink-0" />
            Sign out
          </button>
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Sign out?</DialogTitle>
            <DialogDescription>
              You&apos;ll need to sign in again to access your workspace.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirmOpen(false);
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
