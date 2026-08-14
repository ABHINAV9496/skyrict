/**
 * Identity API client (roles, invitations).
 *
 * All calls go through the same-origin /api/v1/* BFF proxy, which derives the
 * tenant slug from the Host header, forwards the in-memory access token when
 * present, and triggers a silent refresh through the httpOnly session cookie
 * on the first 401 of a page load.
 */

import { apiFetch, apiPost } from "@/lib/api/http";

export interface InvitationSummary {
  id: string;
  email: string;
  roleName: string;
  expiresAt: string;
  usedAt: string | null;
  usedByUserId: string | null;
  createdAt: string;
}

export interface InvitationCreated extends InvitationSummary {
  token: string;
}

export interface RoleSummary {
  id: string;
  name: string;
  permissions: string[];
  isSystemRole: boolean;
  createdAt: string;
}

export interface Member {
  id: string;
  email: string;
  fullName: string;
  roleName: string;
  joinedAt: string | null;
  avatarUrl: string | null;
  isSelf: boolean;
}

export interface Permission {
  key: string;
  description: string;
}

export interface PermissionModule {
  key: string;
  label: string;
  permissions: Permission[];
}

interface InvitationPayload {
  id?: unknown;
  email?: unknown;
  role_name?: unknown;
  expires_at?: unknown;
  used_at?: unknown;
  used_by_user_id?: unknown;
  created_at?: unknown;
  token?: unknown;
}

interface RolePayload {
  id?: unknown;
  name?: unknown;
  permissions?: unknown;
  is_system_role?: unknown;
  created_at?: unknown;
}

interface MemberPayload {
  id?: unknown;
  email?: unknown;
  full_name?: unknown;
  role_name?: unknown;
  joined_at?: unknown;
  avatar_url?: unknown;
  is_self?: unknown;
}

function mapInvitation(raw: InvitationPayload): InvitationSummary {
  return {
    id: String(raw.id ?? ""),
    email: String(raw.email ?? ""),
    roleName: String(raw.role_name ?? ""),
    expiresAt: String(raw.expires_at ?? ""),
    usedAt: raw.used_at ? String(raw.used_at) : null,
    usedByUserId: raw.used_by_user_id ? String(raw.used_by_user_id) : null,
    createdAt: String(raw.created_at ?? ""),
  };
}

function mapInvitationCreated(raw: InvitationPayload): InvitationCreated {
  return { ...mapInvitation(raw), token: String(raw.token ?? "") };
}

function mapRole(raw: RolePayload): RoleSummary {
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    permissions: Array.isArray(raw.permissions)
      ? raw.permissions.map(String)
      : [],
    isSystemRole: Boolean(raw.is_system_role),
    createdAt: String(raw.created_at ?? ""),
  };
}

export async function listInvitations(): Promise<InvitationSummary[]> {
  const items = await apiFetch<InvitationPayload[]>("/api/v1/invitations");
  return (items ?? []).map(mapInvitation);
}

export async function createInvitation(
  email: string,
  roleName: string,
): Promise<InvitationCreated> {
  const raw = await apiPost<InvitationPayload>("/api/v1/invitations", {
    email,
    role_name: roleName,
  });
  return mapInvitationCreated(raw ?? {});
}

export async function expireInvitation(invitationId: string): Promise<void> {
  await apiPost<{ expired: boolean }>(`/api/v1/invitations/${invitationId}/expire`, {});
}

const SYSTEM_ROLE_LABELS: Record<string, string> = {
  tenant_owner: "Owner",
  organization_admin: "Admin",
  department_manager: "Manager",
  standard_user: "Member",
  auditor: "Auditor",
};

const ROLE_BADGE_CLASSES: Record<string, string> = {
  tenant_owner: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  organization_admin: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
  department_manager:
    "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  standard_user: "bg-muted text-muted-foreground ring-1 ring-border",
  auditor: "bg-violet-500/15 text-violet-700 ring-1 ring-violet-500/30 dark:text-violet-400",
};

const DEFAULT_ROLE_BADGE_CLASS = "bg-muted text-muted-foreground ring-1 ring-border";

/** Friendly display label for a role name returned by the API. */
export function roleDisplayName(roleName: string): string {
  const label = SYSTEM_ROLE_LABELS[roleName];
  if (label) return label;
  return roleName
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/** Tailwind classes for a role badge, color-coded so the owner stands apart. */
export function roleBadgeClass(roleName: string): string {
  return ROLE_BADGE_CLASSES[roleName] ?? DEFAULT_ROLE_BADGE_CLASS;
}

/** True when the name is reserved for one of the built-in system roles. */
export function isSystemRoleName(roleName: string): boolean {
  return roleName in SYSTEM_ROLE_LABELS;
}

interface PermissionPayload {
  key?: unknown;
  description?: unknown;
}

interface PermissionModulePayload {
  key?: unknown;
  label?: unknown;
  permissions?: unknown;
}

function mapPermission(raw: PermissionPayload): Permission {
  return {
    key: String(raw.key ?? ""),
    description: String(raw.description ?? ""),
  };
}

function mapPermissionModule(raw: PermissionModulePayload): PermissionModule {
  return {
    key: String(raw.key ?? ""),
    label: String(raw.label ?? ""),
    permissions: Array.isArray(raw.permissions) ? raw.permissions.map(mapPermission) : [],
  };
}

export async function listPermissions(): Promise<PermissionModule[]> {
  const raw = await apiFetch<{ modules?: unknown }>("/api/v1/permissions");
  const modules = raw?.modules;
  return Array.isArray(modules) ? modules.map(mapPermissionModule) : [];
}

export async function createRole(input: {
  name: string;
  permissionKeys: string[];
}): Promise<RoleSummary> {
  const raw = await apiPost<RolePayload>("/api/v1/roles", {
    name: input.name,
    permission_keys: input.permissionKeys,
  });
  return mapRole(raw ?? {});
}

export async function updateRole(
  roleId: string,
  input: { name?: string; permissionKeys?: string[] },
): Promise<RoleSummary> {
  const raw = await apiFetch<RolePayload>(`/api/v1/roles/${roleId}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: input.name,
      permission_keys: input.permissionKeys,
    }),
  });
  return mapRole(raw ?? {});
}

export async function deleteRole(roleId: string): Promise<void> {
  await apiFetch<null>(`/api/v1/roles/${roleId}`, { method: "DELETE" });
}

export async function listRoles(): Promise<RoleSummary[]> {
  const items = await apiFetch<RolePayload[]>("/api/v1/roles");
  return (items ?? []).map(mapRole);
}

function mapMember(payload: MemberPayload): Member {
  return {
    id: typeof payload.id === "string" ? payload.id : "",
    email: typeof payload.email === "string" ? payload.email : "",
    fullName: typeof payload.full_name === "string" ? payload.full_name : "",
    roleName: typeof payload.role_name === "string" ? payload.role_name : "",
    joinedAt:
      typeof payload.joined_at === "string" || payload.joined_at === null
        ? payload.joined_at
        : null,
    avatarUrl:
      typeof payload.avatar_url === "string" ? payload.avatar_url : null,
    isSelf: payload.is_self === true,
  };
}

export async function listMembers(): Promise<Member[]> {
  const items = await apiFetch<MemberPayload[]>("/api/v1/members");
  return (items ?? []).map(mapMember);
}

export async function updateMemberRole(
  memberId: string,
  roleName: string,
): Promise<Member> {
  const raw = await apiFetch<MemberPayload>(`/api/v1/members/${memberId}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role_name: roleName }),
  });
  return mapMember(raw ?? {});
}

export async function removeMember(memberId: string): Promise<void> {
  await apiFetch<null>(`/api/v1/members/${memberId}`, { method: "DELETE" });
}

export interface SessionInfo {
  id: string;
  userAgent: string | null;
  ipAddress: string | null;
  status: string;
  isTrusted: boolean;
  createdAt: string;
  lastActiveAt: string;
  expiresAt: string | null;
  device: string | null;
  deviceType: string | null;
}

interface SessionPayload {
  id?: unknown;
  user_agent?: unknown;
  ip_address?: unknown;
  status?: unknown;
  is_trusted?: unknown;
  created_at?: unknown;
  last_active_at?: unknown;
  expires_at?: unknown;
  device?: unknown;
  device_type?: unknown;
}

function mapSession(payload: SessionPayload): SessionInfo {
  return {
    id: typeof payload.id === "string" ? payload.id : "",
    userAgent: typeof payload.user_agent === "string" ? payload.user_agent : null,
    ipAddress: typeof payload.ip_address === "string" ? payload.ip_address : null,
    status: typeof payload.status === "string" ? payload.status : "active",
    isTrusted: payload.is_trusted === true,
    createdAt:
      typeof payload.created_at === "string" ? payload.created_at : new Date().toISOString(),
    lastActiveAt:
      typeof payload.last_active_at === "string"
        ? payload.last_active_at
        : new Date().toISOString(),
    expiresAt:
      typeof payload.expires_at === "string" || payload.expires_at === null
        ? payload.expires_at
        : null,
    device: typeof payload.device === "string" ? payload.device : null,
    deviceType: typeof payload.device_type === "string" ? payload.device_type : null,
  };
}

/** List a member's active sessions in this workspace (admin/auditor surface). */
export async function listMemberSessions(memberId: string): Promise<SessionInfo[]> {
  const raw = await apiFetch<{ sessions?: SessionPayload[] }>(
    `/api/v1/members/${memberId}/sessions`,
  );
  return Array.isArray(raw?.sessions) ? raw.sessions.map(mapSession) : [];
}

/** Log a member out of a single device. */
export async function revokeMemberSession(
  memberId: string,
  sessionId: string,
): Promise<void> {
  await apiFetch<null>(`/api/v1/members/${memberId}/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

/** Log a member out of every device in this workspace. */
export async function revokeAllMemberSessions(memberId: string): Promise<void> {
  await apiFetch<null>(`/api/v1/members/${memberId}/sessions`, {
    method: "DELETE",
  });
}

export interface MyRoles {
  roles: string[];
  permissions: string[];
}

/** The current user's role names and effective permissions in this tenant. */
export async function getMyRoles(): Promise<MyRoles> {
  const raw = await apiFetch<{ roles?: unknown; permissions?: unknown } | null>(
    "/api/v1/roles/me",
  );
  return {
    roles: Array.isArray(raw?.roles) ? raw.roles.map(String) : [],
    permissions: Array.isArray(raw?.permissions) ? raw.permissions.map(String) : [],
  };
}
