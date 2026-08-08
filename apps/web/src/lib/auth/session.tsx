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
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

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
  }, []);

  const value = useMemo(
    () => ({ status, user, restore, logout }),
    [status, user, restore, logout],
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
