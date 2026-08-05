/**
 * Auth API seam.
 *
 * The onboarding wizard (SKY-30) calls the real identity service — every
 * /auth/signup/* endpoint mirrors the backend contract and returns a typed
 * result. Login, password reset, and MFA are still simulated until their
 * tickets land; their functions below keep returning mock data.
 */

import { env } from "@/config/env";

export interface AuthUser {
  id: string;
  email: string;
  fullName: string;
  isActive: boolean;
  isVerified: boolean;
  mfaEnabled: boolean;
  createdAt: string;
}

export interface AuthSession {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  tokenType: "Bearer";
  user: AuthUser;
}

export type LoginResult =
  | { status: "ok"; session: AuthSession }
  | { status: "mfa_required"; mfaToken: string }
  | { status: "email_unverified"; email: string };

export type ResetRequestResult = { status: "sent"; email: string };

export type ResetConfirmResult = { status: "ok" };

export type VerifyMfaResult =
  | { status: "ok"; session: AuthSession }
  | { status: "invalid" };

const delay = (ms = 700) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

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
// Mocked until their tickets land: login, password reset, MFA
// ---------------------------------------------------------------------------

export async function loginEmailPassword(input: {
  email: string;
  password: string;
}): Promise<LoginResult> {
  await delay();
  const session: AuthSession = {
    accessToken: "demo-access-token",
    refreshToken: "demo-refresh-token",
    expiresIn: 3600,
    tokenType: "Bearer",
    user: {
      id: "demo-user",
      email: input.email,
      fullName: "Demo User",
      isActive: true,
      isVerified: true,
      mfaEnabled: false,
      createdAt: new Date().toISOString(),
    },
  };
  return { status: "ok", session };
}

export async function requestPasswordReset(input: {
  email: string;
}): Promise<ResetRequestResult> {
  await delay();
  return { status: "sent", email: input.email };
}

export async function confirmPasswordReset(input: {
  token: string;
  newPassword: string;
}): Promise<ResetConfirmResult> {
  void input;
  await delay();
  return { status: "ok" };
}

export async function verifyMfa(input: {
  code: string;
  mfaToken: string;
  isBackupCode?: boolean;
}): Promise<VerifyMfaResult> {
  void input;
  await delay();
  return { status: "invalid" };
}

// ---------------------------------------------------------------------------
// Onboarding wizard (real /auth/signup/* endpoints)
// ---------------------------------------------------------------------------

export const DEMO_MFA_CODE = "123456";

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
// Mandatory MFA setup (still simulated — backend wiring is a separate ticket)
// ---------------------------------------------------------------------------

export interface MfaSetup {
  secret: string;
  otpauthUri: string;
  backupCodes: string[];
}

const BACKUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function randomBase32(bytes: number): string {
  const values = new Uint8Array(bytes);
  crypto.getRandomValues(values);
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0;
  let value = 0;
  let output = "";
  for (const byte of values) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      output += alphabet[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits > 0) {
    output += alphabet[(value << (5 - bits)) & 31];
  }
  return output;
}

function randomBackupCodes(count: number): string[] {
  return Array.from({ length: count }, () => {
    const chars = Array.from(
      { length: 10 },
      () =>
        BACKUP_CODE_ALPHABET[
          Math.floor(Math.random() * BACKUP_CODE_ALPHABET.length)
        ],
    );
    return `${chars.slice(0, 5).join("")}-${chars.slice(5).join("")}`;
  });
}

export async function setupMfa(input: { email: string }): Promise<MfaSetup> {
  await delay(700);
  const secret = randomBase32(20).replace(/=+$/, "");
  const otpauthUri = `otpauth://totp/Skyrict:${encodeURIComponent(
    input.email,
  )}?secret=${secret}&issuer=Skyrict&period=30&digits=6`;
  return {
    secret,
    otpauthUri,
    backupCodes: randomBackupCodes(10),
  };
}

export async function confirmMfaSetup(input: {
  code: string;
  secret: string;
}): Promise<{ status: "ok" } | { status: "invalid" }> {
  void input.secret;
  await delay(700);
  if (input.code === DEMO_MFA_CODE) return { status: "ok" };
  return { status: "invalid" };
}
