"use client";

import { useEffect, useState } from "react";

import { getMyRoles } from "@/lib/api/identity-api";

export type ModuleKey = "erp" | "agents" | "intelligence";

export interface ModuleAccess {
  erp: boolean;
  agents: boolean;
  intelligence: boolean;
}

export type AccessStatus = "loading" | "ready" | "error";

export interface ModuleAccessState {
  status: AccessStatus;
  access: ModuleAccess;
  roles: string[];
  permissions: string[];
}

const WILDCARD = "*";
const AGENTS_READ = "agents:read";
const INTELLIGENCE_READ = "intelligence:read";

export const MODULE_ORDER: ModuleKey[] = ["agents", "erp", "intelligence"];

const NO_ACCESS: ModuleAccess = { erp: false, agents: false, intelligence: false };

/**
 * Derive module access from a user's effective permission set. The wildcard
 * grants every module; otherwise each module requires its own key/prefix.
 */
export function resolveModuleAccess(permissions: string[]): ModuleAccess {
  const set = new Set(permissions);
  const all = set.has(WILDCARD);
  return {
    erp: all || permissions.some((permission) => permission.startsWith("erp.")),
    agents: all || set.has(AGENTS_READ),
    intelligence: all || set.has(INTELLIGENCE_READ),
  };
}

export function accessibleModules(access: ModuleAccess): ModuleKey[] {
  return MODULE_ORDER.filter((key) => access[key]);
}

const INITIAL_STATE: ModuleAccessState = {
  status: "loading",
  access: NO_ACCESS,
  roles: [],
  permissions: [],
};

let inFlight: Promise<ModuleAccessState> | null = null;

function fetchAccessState(): Promise<ModuleAccessState> {
  if (inFlight) return inFlight;
  inFlight = getMyRoles()
    .then((data) => ({
      status: "ready" as const,
      access: resolveModuleAccess(data.permissions),
      roles: data.roles,
      permissions: data.permissions,
    }))
    .catch(() => ({
      status: "error" as const,
      access: NO_ACCESS,
      roles: [],
      permissions: [],
    }))
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/**
 * Single-flight resolver so the shell, sidebar, and overview share one
 * /roles/me request per page load instead of issuing parallel calls.
 */
export async function getModuleAccess(): Promise<ModuleAccessState> {
  return fetchAccessState();
}

/** Subscribe to module access. State settles once, then stays cached for the session. */
export function useModuleAccess(): ModuleAccessState {
  const [state, setState] = useState<ModuleAccessState>(INITIAL_STATE);

  useEffect(() => {
    let cancelled = false;
    void fetchAccessState().then((next) => {
      if (!cancelled) setState(next);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
