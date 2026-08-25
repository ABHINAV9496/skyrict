"use client";

import { LogOut } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/auth/session";

/**
 * The self-service leave portal chrome: brand, the signed-in identity and a
 * sign-out control only. Deliberately NOT the workspace dashboard — sole
 * holders of the employee_self_service role land here with no ERP navigation
 * to bounce off, matching their single permission.
 */
export function PortalShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useSession();

  return (
    <div className="flex min-h-dvh flex-col bg-muted/30">
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-3 px-4">
          <Logo tone="sky" />
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {user?.email}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void logout()}
            >
              <LogOut aria-hidden="true" className="size-4" />
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        {children}
        <p className="sr-only">{`Signed in as ${user?.email ?? "you"}`}</p>
      </main>
    </div>
  );
}
