"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { AuthUser } from "@/lib/api/auth-api";
import { ensureSession } from "@/lib/api/http";
import { getAccessToken, setAccessToken } from "@/lib/auth/session-store";

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

interface SessionContextValue {
  status: SessionStatus;
  user: AuthUser | null;
  /** Re-hydrate the in-memory access token + profile from the BFF. */
  restore: () => Promise<void>;
  /** Replace the in-memory profile (e.g. after an avatar change). */
  updateUser: (user: AuthUser) => void;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/**
 * Absolute `{slug}.signin.{apex}:{port}/signin` URL for the current origin,
 * mirroring the middleware's cross-surface routing. Falls back to the current
 * origin's `/signin` when there is no tenant label (dev without a subdomain).
 */
function browserSigninUrl(): string {
  const { protocol, hostname, port } = window.location;
  const host = hostname.toLowerCase();
  const portSuffix = port ? `:${port}` : "";
  if (host.includes(".signin.")) return `${protocol}//${host}${portSuffix}/signin`;
  const apex = host.split(".").slice(1).join(".");
  if (!apex) return `${protocol}//${host}${portSuffix}/signin`;
  const slug = host.split(".")[0];
  return `${protocol}//${slug}.signin.${apex}${portSuffix}/signin`;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  const restore = useCallback(async () => {
    try {
      // Single-flight with the /api/v1 client: exactly one server-side token
      // rotation per page load, so parallel hydrations never race the refresh
      // token (a reuse would revoke the whole token family).
      const session = await ensureSession();
      if (session) {
        setAccessToken(session.accessToken);
        setUser((session.user as AuthUser | null) ?? null);
        setStatus("authenticated");
      } else {
        setAccessToken(null);
        setUser(null);
        setStatus("unauthenticated");
      }
    } catch {
      setAccessToken(null);
      setUser(null);
      setStatus("unauthenticated");
    }
  }, []);

  useEffect(() => {
    void restore();
  }, [restore]);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessToken: getAccessToken() }),
      });
    } catch {
      // Best-effort: the cookie is cleared client-side regardless.
    }
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
    // Leave the workspace origin immediately so the user lands on the tenant's
    // signin surface instead of lingering on a page with no session.
    window.location.assign(browserSigninUrl());
  }, []);

  const updateUser = useCallback((next: AuthUser) => {
    setUser(next);
  }, []);

  const value = useMemo(
    () => ({ status, user, restore, updateUser, logout }),
    [status, user, restore, updateUser, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return context;
}
