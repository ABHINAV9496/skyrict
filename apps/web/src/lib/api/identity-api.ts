/**
 * Identity API client (roles, onboarding, invitations).
 *
 * All calls go through the same-origin /api/v1/* BFF proxy, which derives the
 * tenant slug from the Host header, forwards the in-memory access token when
 * present, and triggers a silent refresh through the httpOnly session cookie
 * on the first 401 of a page load.
 */

import { apiFetch, apiPost } from "@/lib/api/http";

export interface MyRoles {
  roles: string[];
  permissions: string[];
}

export interface CurrentUserProfile {
  id: string;
  email: string;
  fullName: string;
  isActive: boolean;
  isVerified: boolean;
  mfaEnabled: boolean;
  onboardingDismissedAt: string | null;
  createdAt: string;
}

export interface OrganizationProfile {
  id: string;
  name: string;
  slug: string;
  isActive: boolean;
  planTier: string;
  onboardingCompletedAt: string | null;
  createdAt: string;
}

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

interface UserPayload {
  id?: unknown;
  email?: unknown;
  full_name?: unknown;
  is_active?: unknown;
  is_verified?: unknown;
  mfa_enabled?: unknown;
  onboarding_dismissed_at?: unknown;
  created_at?: unknown;
}

interface TenantPayload {
  id?: unknown;
  name?: unknown;
  slug?: unknown;
  is_active?: unknown;
  plan_tier?: unknown;
  onboarding_completed_at?: unknown;
  created_at?: unknown;
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

function mapUser(raw: UserPayload): CurrentUserProfile {
  return {
    id: String(raw.id ?? ""),
    email: String(raw.email ?? ""),
    fullName: String(raw.full_name ?? ""),
    isActive: Boolean(raw.is_active),
    isVerified: Boolean(raw.is_verified),
    mfaEnabled: Boolean(raw.mfa_enabled),
    onboardingDismissedAt: raw.onboarding_dismissed_at
      ? String(raw.onboarding_dismissed_at)
      : null,
    createdAt: String(raw.created_at ?? ""),
  };
}

function mapTenant(raw: TenantPayload): OrganizationProfile {
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    slug: String(raw.slug ?? ""),
    isActive: Boolean(raw.is_active),
    planTier: String(raw.plan_tier ?? ""),
    onboardingCompletedAt: raw.onboarding_completed_at
      ? String(raw.onboarding_completed_at)
      : null,
    createdAt: String(raw.created_at ?? ""),
  };
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

export async function getMyRoles(): Promise<MyRoles> {
  return apiFetch<MyRoles>("/api/v1/roles/me");
}

export async function getMyProfile(): Promise<CurrentUserProfile> {
  const raw = await apiFetch<UserPayload>("/api/v1/users/me");
  return mapUser(raw ?? {});
}

export async function getMyOrganization(): Promise<OrganizationProfile> {
  const raw = await apiFetch<TenantPayload>("/api/v1/organizations/me");
  return mapTenant(raw ?? {});
}

export async function dismissOnboarding(): Promise<CurrentUserProfile> {
  const raw = await apiPost<UserPayload>("/api/v1/users/me/onboarding/dismiss", {});
  return mapUser(raw ?? {});
}

export async function completeOnboarding(): Promise<OrganizationProfile> {
  const raw = await apiPost<TenantPayload>("/api/v1/organizations/me/onboarding/complete", {});
  return mapTenant(raw ?? {});
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

export async function listRoles(): Promise<RoleSummary[]> {
  const items = await apiFetch<RolePayload[]>("/api/v1/roles");
  return (items ?? []).map(mapRole);
}
