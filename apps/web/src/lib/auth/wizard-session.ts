/**
 * In-memory wizard credentials (browser only).
 *
 * The onboarding wizard never issues tokens: POST /auth/signup/organization
 * returns none. To reach the authenticated /mfa/setup + /mfa/verify endpoints
 * after provisioning, we keep the just-set password in memory from the
 * security step and auto-login once the organization exists. The password is
 * cleared as soon as it's consumed (and never touches localStorage).
 */

let email: string | null = null;
let password: string | null = null;

export function setWizardCredentials(creds: { email: string; password: string }): void {
  email = creds.email;
  password = creds.password;
}

export function consumeWizardCredentials(): { email: string; password: string } | null {
  if (!email || !password) return null;
  const creds = { email, password };
  email = null;
  password = null;
  return creds;
}

export function clearWizardCredentials(): void {
  email = null;
  password = null;
}
