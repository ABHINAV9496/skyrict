/**
 * Auth API seam.
 *
 * Every function mirrors the backend contract (Skyrict identity service:
 * POST /auth/login, /auth/register, /auth/refresh, /auth/logout, MFA, etc.)
 * but currently simulates the network call and returns a typed result.
 *
 * To wire the real API: replace each body with a fetch() against the
 * configured base URL and return the same type. UI code does not change.
 */

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

export type RegisterResult = { status: "check_email"; email: string };

export type ResetRequestResult = { status: "sent"; email: string };

export type ResetConfirmResult = { status: "ok" };

export type VerifyEmailResult = { status: "verified" } | { status: "invalid" };

export type ResendResult = { status: "sent"; email: string };

export type VerifyMfaResult =
  | { status: "ok"; session: AuthSession }
  | { status: "invalid" };

const delay = (ms = 700) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

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

export async function register(input: {
  email: string;
  password: string;
  fullName: string;
  tenantSlug?: string;
}): Promise<RegisterResult> {
  await delay();
  return { status: "check_email", email: input.email };
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

export async function verifyEmail(input: {
  token: string;
}): Promise<VerifyEmailResult> {
  await delay(900);
  if (!input.token) return { status: "invalid" };
  return { status: "verified" };
}

export async function resendVerificationEmail(input: {
  email: string;
}): Promise<ResendResult> {
  await delay();
  return { status: "sent", email: input.email };
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
// Onboarding wizard (simulated)
// ---------------------------------------------------------------------------

export const DEMO_VERIFICATION_CODE = "123456";
export const DEMO_MFA_CODE = "123456";

export interface RiskAssessment {
  requiresCaptcha: boolean;
  signals: string[];
}

export async function assessRisk(): Promise<RiskAssessment> {
  await delay(350);
  return { requiresCaptcha: false, signals: [] };
}

export async function solveCaptcha(): Promise<{ status: "ok" }> {
  await delay(900);
  return { status: "ok" };
}

export async function checkEmailAvailability(input: {
  email: string;
}): Promise<{ available: boolean }> {
  await delay(500);
  const reserved = new Set([
    "taken@skyrict.com",
    "admin@skyrict.com",
    "sales@skyrict.com",
  ]);
  return { available: !reserved.has(input.email.toLowerCase()) };
}

export async function requestVerificationCode(input: {
  email: string;
}): Promise<{ status: "sent"; email: string; resendIn: number }> {
  await delay(650);
  return { status: "sent", email: input.email, resendIn: 60 };
}

export type VerifyEmailCodeResult =
  | { status: "ok"; verificationToken: string }
  | { status: "invalid" }
  | { status: "expired" };

export async function verifyEmailCode(input: {
  email: string;
  code: string;
}): Promise<VerifyEmailCodeResult> {
  void input.email;
  await delay(700);
  if (input.code === DEMO_VERIFICATION_CODE) {
    return { status: "ok", verificationToken: "demo-verification-token" };
  }
  return { status: "invalid" };
}

export async function checkWorkspaceSlug(input: {
  slug: string;
}): Promise<{ available: boolean }> {
  await delay(450);
  const reserved = new Set([
    "skyrict",
    "www",
    "admin",
    "api",
    "support",
    "demo",
    "billing",
  ]);
  return { available: !reserved.has(input.slug.toLowerCase()) };
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
): Promise<{ status: "ok" }> {
  void input;
  await delay(1000);
  return { status: "ok" };
}

export async function completeSecurityStep(input: {
  email: string;
  verificationToken: string;
  password: string;
}): Promise<{ status: "ok" }> {
  void input;
  await delay(800);
  return { status: "ok" };
}

// ---------------------------------------------------------------------------
// Mandatory MFA setup (simulated)
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

export async function setupMfa(input: {
  email: string;
}): Promise<MfaSetup> {
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
