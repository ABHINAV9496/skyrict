/**
 * Auth API seam.
 *
 * Login and MFA verification go through the BFF route handlers
 * (/api/auth/*), which set the httpOnly refresh-token cookie and hand the
 * access token back in the body — the browser keeps it in memory only.
 * Onboarding stays on the real /auth/signup/* endpoints directly.
 */

import { env } from "@/config/env";
import { ApiError, apiPost } from "@/lib/api/http";
import { setAccessToken } from "@/lib/auth/session-store";

export { ApiError };

export interface AuthUser {
  id: string;
  email: string;
  fullName: string;
  isActive: boolean;
  isVerified: boolean;
  mfaEnabled: boolean;
  createdAt: string;
}

export type LoginResult =
  | { status: "authenticated"; accessToken: string; expiresIn: number; user: AuthUser }
  | { status: "mfa_setup"; accessToken: string; expiresIn: number; user: AuthUser }
  | { status: "mfa_challenge"; mfaToken: string; user: AuthUser };

export type VerifyMfaResult =
  | { status: "ok"; accessToken: string; expiresIn: number; user: AuthUser }
  | { status: "invalid" };

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${env.apiBaseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Network error — check your connection and try again.");
  }

  let payload: {
    data?: T | null;
    detail?: { error?: { message?: string }; message?: string };
  };
  try {
    payload = await res.json();
  } catch {
    payload = {};
  }

  if (!res.ok) {
    const message =
      payload.detail?.error?.message ??
      payload.detail?.message ??
      "Request failed. Please try again.";
    throw new ApiError(res.status, message);
  }
  return payload.data as T;
}

// ---------------------------------------------------------------------------
// Sign in
// ---------------------------------------------------------------------------

interface BffLoginResponse {
  status: "authenticated" | "mfa_setup" | "mfa_challenge";
  accessToken?: string | null;
  expiresIn?: number;
  mfaToken?: string | null;
  user?: AuthUser | null;
  error?: string;
}

export async function loginEmailPassword(input: {
  email: string;
  password: string;
}): Promise<LoginResult> {
  let response: Response;
  try {
    response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch {
    throw new ApiError(0, "Network error — check your connection and try again.");
  }

  const payload = (await response.json().catch(() => ({}))) as BffLoginResponse;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload.error ?? "Unable to sign in. Check your credentials and try again.",
    );
  }

  if (payload.status === "mfa_challenge") {
    setAccessToken(null);
    if (!payload.mfaToken || !payload.user) {
      throw new ApiError(502, "Unexpected login response.");
    }
    return {
      status: "mfa_challenge",
      mfaToken: payload.mfaToken,
      user: payload.user,
    };
  }

  if (!payload.accessToken || !payload.user) {
    throw new ApiError(502, "Unexpected login response.");
  }
  setAccessToken(payload.accessToken);
  return {
    status: payload.status === "mfa_setup" ? "mfa_setup" : "authenticated",
    accessToken: payload.accessToken,
    expiresIn: payload.expiresIn ?? 0,
    user: payload.user,
  };
}

interface BffMfaVerifyResponse {
  status: "authenticated";
  accessToken?: string | null;
  expiresIn?: number;
  user?: AuthUser | null;
  error?: string;
}

export async function verifyMfa(input: {
  code: string;
  mfaToken: string;
}): Promise<VerifyMfaResult> {
  let response: Response;
  try {
    response = await fetch("/api/auth/mfa/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mfa_token: input.mfaToken, code: input.code }),
    });
  } catch {
    throw new ApiError(0, "Network error — check your connection and try again.");
  }

  const payload = (await response.json().catch(() => ({}))) as BffMfaVerifyResponse;
  if (response.status === 401 || response.status === 403) {
    return { status: "invalid" };
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload.error ?? "Unable to verify the code.",
    );
  }
  if (!payload.accessToken || !payload.user) {
    throw new ApiError(502, "Unexpected verification response.");
  }
  setAccessToken(payload.accessToken);
  return {
    status: "ok",
    accessToken: payload.accessToken,
    expiresIn: payload.expiresIn ?? 0,
    user: payload.user,
  };
}

// ---------------------------------------------------------------------------
// Onboarding wizard (real /auth/signup/* endpoints)
// ---------------------------------------------------------------------------

export interface RiskAssessment {
  requiresCaptcha: boolean;
  requiresChallenge: boolean;
  signals: string[];
}

export async function assessRisk(): Promise<RiskAssessment> {
  return {
    requiresCaptcha: true,
    requiresChallenge: false,
    signals: [],
  };
}

export async function solveCaptcha(): Promise<{ status: "ok" }> {
  return { status: "ok" };
}

export async function signupStart(input: {
  email: string;
  turnstileToken?: string;
}): Promise<{ status: "ok" }> {
  return post<{ status: "ok" }>("/auth/signup/start", {
    email: input.email,
    turnstileToken: input.turnstileToken,
  });
}

export async function checkEmailAvailability(input: {
  email: string;
}): Promise<{ available: boolean }> {
  return post<{ available: boolean }>("/auth/signup/check-email", {
    email: input.email,
  });
}

export async function requestVerificationCode(input: {
  email: string;
}): Promise<{
  status: "ok";
  resendIn: number;
  code?: string | null;
}> {
  const data = await post<{ status: "ok"; resendIn: number; code?: string | null }>(
    "/auth/signup/send-code",
    { email: input.email },
  );
  return data;
}

export type VerifyEmailCodeResult =
  | { status: "ok"; verificationToken: string }
  | { status: "invalid" }
  | { status: "expired" };

export async function verifyEmailCode(input: {
  email: string;
  code: string;
}): Promise<VerifyEmailCodeResult> {
  const data = await post<{
    status: "ok" | "invalid" | "expired";
    verificationToken?: string | null;
  }>("/auth/signup/verify-code", { email: input.email, code: input.code });
  if (data.status === "ok" && data.verificationToken) {
    return { status: "ok", verificationToken: data.verificationToken };
  }
  if (data.status === "expired") {
    return { status: "expired" };
  }
  return { status: "invalid" };
}

export async function completeSecurityStep(input: {
  email: string;
  verificationToken: string;
  password: string;
}): Promise<{ status: "ok" }> {
  return post<{ status: "ok" }>("/auth/signup/password", {
    email: input.email,
    verificationToken: input.verificationToken,
    password: input.password,
  });
}

export async function checkWorkspaceSlug(input: {
  slug: string;
}): Promise<{ available: boolean }> {
  return post<{ available: boolean }>("/auth/signup/check-slug", {
    slug: input.slug,
  });
}

export interface CreateOrganizationInput {
  email: string;
  verificationToken: string;
  planId: string;
  companyName: string;
  industry: string;
  workspaceSlug: string;
  ownerFullName: string;
  phoneCountry: string;
  phoneNumber: string;
  address: {
    country: string;
    addressLine1: string;
    addressLine2?: string;
    city: string;
    state: string;
    postalCode: string;
  };
}

export async function createOrganization(
  input: CreateOrganizationInput,
): Promise<{ status: "ok"; mfaRequired: boolean }> {
  return post<{ status: "ok"; mfaRequired: boolean }>("/auth/signup/organization", {
    email: input.email,
    verificationToken: input.verificationToken,
    planId: input.planId,
    companyName: input.companyName,
    industry: input.industry,
    workspaceSlug: input.workspaceSlug,
    ownerFullName: input.ownerFullName,
    phoneCountry: input.phoneCountry,
    phoneNumber: input.phoneNumber,
    address: input.address,
  });
}

// ---------------------------------------------------------------------------
// Mandatory MFA enrollment (authenticated /mfa/* endpoints)
// ---------------------------------------------------------------------------

export interface MfaSetup {
  secret: string;
  otpauthUri: string;
  backupCodes: string[];
}

export async function setupMfa(): Promise<MfaSetup> {
  const data = await apiPost<{
    secret: string;
    provisioning_uri: string;
    backup_codes: string[];
  }>("/api/v1/mfa/setup", undefined);
  return {
    secret: data.secret,
    otpauthUri: data.provisioning_uri,
    backupCodes: data.backup_codes,
  };
}

export async function confirmMfaSetup(input: {
  code: string;
}): Promise<{ status: "ok" } | { status: "invalid" }> {
  try {
    await apiPost<{ verified: boolean }>("/api/v1/mfa/verify", { code: input.code });
    return { status: "ok" };
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      return { status: "invalid" };
    }
    throw err;
  }
}
