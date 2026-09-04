# Production Auth Model - Implementation Plan

## Status

In progress (security review applied - see "Security review" sections).

## Goal

Ship production-grade auth on skyrict: **4 subdomain routes** (marketing, register, login, workspace), register-only marketing site, per-company tenants, owner sets password at registration, members set theirs via invite link, **MFA mandatory for all tenant users**, role-based dashboard on `{slug}.localhost/dashboard`, and a hardened 2026 security posture (no visible endpoints, no tokens in URLs, host-locked handoff).

## URL Architecture (4 subdomain routes)

| # | Surface | Dev | Prod |
|---|---|---|---|
| 1 | Marketing | `web.localhost` | `web.skyrict.com` |
| 2 | Register | `signup.localhost/signup` | `signup.skyrict.com/signup` |
| 2b | Invite accept | `signup.localhost/invite#t=...` | `signup.skyrict.com/invite#t=...` |
| 3 | Login | `{slug}.signin.localhost/signin` | `{slug}.signin.skyrict.com/signin` |
| 4 | Workspace | `{slug}.localhost/dashboard` | `{slug}.skyrict.com/dashboard` |

- No `request_type` param (the path is the mode). Dashboard URL **never contains `signin`**.
- Dev: one Next app on `:3000`, Host-based routing; `resolveTenantSlug` = `^([a-z0-9-]+)\.(signin\.)?(localhost|skyrict\.com)$`, **no fallback**; `web.*`/`signup.*` → no slug.
- Prod: `web.skyrict.com`, `signup.skyrict.com`, wildcard `*.skyrict.com` + `*.signin.skyrict.com`, wildcard TLS.

### Security review - applied to URL architecture

- **Host allowlist (High).** `resolveTenantSlug` derives the slug from `Host`, but the BFF and middleware must also **reject unknown hosts** (DNS-rebinding / host-header injection). Dev: allow `*.localhost` + `localhost` only. Prod: allow `*.skyrict.com`, `*.signin.skyrict.com` + exact apex names. The reverse proxy must also drop unknown `Host` (nginx `default_server` → 444). The regex is a *parser*, the allowlist is the *gate*.
- **No env fallback for the slug.** `TENANT_SLUG` / `NEXT_PUBLIC_TENANT_SLUG` are dev-only conveniences and must not exist in the production posture. The slug always comes from the validated `Host`.

## Flows

### Register (owner) - marketing is register-only
```
web.localhost (no Log in) → Get started → signup.localhost/signup
  Email + Turnstile → "Continue with email" (disabled till Turnstile passes)
    ├─ registered email → "This email is unavailable."  <- stop, no sign-in hint
    └─ new email → OTP (email verification, silent, no "verified" screen)
         wizard: Plan → Set password (owner) → Organization (creates tenant,
                 owner session)
         → signup.localhost/setup-mfa (QR + confirm code + backup codes)
         → handoff (POST body) → {slug}.localhost/api/auth/handoff → 307
         → URL bar: {slug}.localhost/dashboard
```

### Login (owner & member)
```
{slug}.signin.localhost/signin
  Email + Password (BOTH required, uniform "check your credentials" errors - no enumeration)
  → MFA ALWAYS (mfa_token challenge → TOTP/backup code); not enrolled → /setup-mfa
  → session stores IP, device name, user-agent, last_active
  → handoff (POST body) → {slug}.localhost/api/auth/handoff → 307
  → URL bar: {slug}.localhost/dashboard
```

### Invite (member)
```
Owner (Members page) sends invite → email link signup.localhost/invite#t=<single-use>
  click → JS reads fragment, POSTs token to /api/auth/invite/resolve (body only)
       → read-only "You're joining <org> as <email>" (email never typed)
  form: Full Name + Password + Confirm (client-validated, min 12)
  → /api/auth/invite/accept {token, password, full_name} → user created
     (email server-side from stored invite), role granted, session MFA-pending
  → signup.localhost/setup-mfa (authenticator QR + confirm) → handoff
  → URL bar: {slug}.localhost/dashboard   (role-filtered nav)
  abandoned setup → MFA-pending at next login; consumed invite → re-invite
```

### Security review - applied to flows

- **Server-side password strength (Medium).** Min 12 for both owner (signup) and member (invite) is enforced server-side, plus a strength check (reject password == email / full name / company, common-password list). Client-only validation is decoration.
- **Reset password: MFA must survive the reset; sessions must not (High).** Password reset **never disables MFA** (otherwise email compromise = account takeover even with MFA enrolled). Reset revokes all sessions/token families, uses the same fragment + POST-body token discipline, and re-login requires MFA again. Rule stated explicitly here so no future change disables MFA on reset.
- **Invite resolve/accept hardening (Medium).** Rate-limit `/invitations/resolve` + `/accept` per IP *and* per token. `resolve` returns one generic "invalid or expired" - no distinction between "used", "expired", "unknown". Explicit TTL (7 days) + single-use + revoked on membership changes. Role comes from the **stored invite**, never from the client request.
- **MFA enrollment verification is brute-force guarded (Medium).** `/mfa/verify` (the setup-confirm endpoint) is rate-limited per IP *and* per user, and enforces a Redis-backed failed-attempt lockout (`MFA_ENROLL_MAX_ATTEMPTS=5`, 5-minute window) - repeated wrong codes return 429 and must wait out the window. The attempt counter resets on success and TTL-expires on its own.
- **Backup codes rotate without touching TOTP (Medium).** `POST /mfa/backup-codes` (rate-limited per IP+user) replaces the stored code set with 10 fresh hashes - the TOTP secret and `mfa_enabled` state are untouched. Rotating is an authenticated, MFA-complete action, so it is gated by the enforcement gate; old codes are rejected immediately at the login challenge. The BFF exposes this as `/api/auth/mfa/backup-codes`, and the setup panel offers Copy all / Download / Regenerate (regenerate swaps the list and requires a fresh acknowledgment).

## Key Mechanisms

- **Handoff**: auth origins (`signup.localhost`, `{slug}.signin.localhost`) never hold the workspace session. Every completed auth mints a single-use, ~120s, **tenant-bound** token (POST body only) that `{slug}.localhost/api/auth/handoff` exchanges for a host-scoped httpOnly cookie, then 307 → `/dashboard`. Same pipeline for register/login/invite. (Dev `.localhost` is a PSL suffix → no cross-subdomain cookies; prod keeps per-tenant host-scoped cookies for isolation.)
- **BFF**: browser never talks to the identity service directly; all calls go through same-origin, origin-checked Next.js route handlers. Access token stays in memory; refresh token in httpOnly cookie.

### Security review - applied to mechanisms

- **Handoff is server-committed, not request-driven (High).** `{destination_slug, tenant_id, user_id, redirect}` live **inside the token**; the 307 target is built from the token, never from the request. Prevents request-side steering of the redirect (open-redirect class).
- **Atomic single-use (High).** Redemption consumes via `GETDEL` (or Lua) so a raced double-submit cannot mint two sessions.
- **Rate-limited redemption (High).** Rate-limit the handoff *redemption* per IP, in addition to mint-side limits.
- **Minted only after MFA completes (High).** The handoff token for login/invite is issued only after the MFA challenge (or mandatory-enrollment setup) succeeds - never on password-alone.
- **`__Host-` cookie prefix in prod (High).** `__Host-skyrict_session` (Secure + Path=/ + no Domain) matches the host-scoped requirement exactly. Dev keeps plain `skyrict_session` (http).
- **BFF responses are `Cache-Control: no-store` (High).** `login`, `mfa/verify`, `handoff`, `session`, `refresh`, `code/*`, `org`, `invite/*` must not be cached (Next route handlers do not set this by default); add `Vary: Origin` where responses depend on origin.
- **Redirect validation with URL parsing, not prefix matching (High).** Any `next`-style parameter is allowlisted by `new URL(next, requestBase)` requiring identical origin + path prefix check - string-prefix checks are bypassed by `\evil.com`, `//evil.com`, encoded slashes. Allowlisted to `/dashboard/*` only.
- **Access-token revocation (High).** Access tokens carry a `sid` claim; `get_current_user` checks the session row (`status = 'active'`, not expired) with one indexed lookup → revoked sessions are denied immediately, not after TTL. The whole **token family** is revoked on logout, password change, MFA disable, and owner-assisted MFA reset.

## Security Posture (2026)

1. Delete the public `/api/v1` rewrite (`next.config.js:8`) - backend unreachable from the browser.
2. No tokens/emails in URLs - handoff POST bodies; invite/reset tokens in URL **fragment** + POST body (never query, never server-logged). Redirect targets are token-embedded and validated by URL parsing (see mechanisms).
3. Host/origin locking - handoff rejects `token.tenant != Host tenant`; `assertSameOrigin` CSRF gate on state-changing BFF routes; host allowlist gates every tenant resolution.
4. Cookies host-scoped to the exact tenant subdomain, httpOnly, SameSite=Lax, `secure` in prod, `__Host-` prefix in prod.
5. Handoff rate-limited + single-use (atomic) + 120s TTL; invite tokens hash-only storage; backup codes hash-only + consumed atomically; `/mfa/verify` enrollment has a per-user failed-attempt lockout; backup codes rotate independently of the TOTP secret.
6. Generic error messages (no stack traces/internal paths); tokens redacted in logs (log hash prefixes only).
7. Headers: `Referrer-Policy: no-referrer`, CSP (`frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, `script-src 'self' https://challenges.cloudflare.com` for Turnstile), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Opener-Policy: same-origin`, HSTS (prod).
8. Drop `X-Tenant-Slug` from the browser (BFF derives slug from Host).
9. **Auth pages and BFF responses are `no-store`** (see mechanisms) - prevents bfcache/proxy replay of auth state.
10. **Step-up re-auth for sensitive operations (Medium).** Disabling MFA, changing email, "revoke all sessions" require current password or a fresh TOTP.
11. **Unknown tenant is generic (Medium).** `{slug}.signin.localhost` for a nonexistent/disabled tenant renders one generic "workspace not found" - no distinguishable "doesn't exist" vs "disabled" wording.
12. **Enumeration surfaces rate-limited (Low).** `check-slug` / `check-email` are UX-necessary oracles; rate-limit them like login.

## Phases

### Phase 0 - Pull PR #47 (backend security fixes)
1. Commit current BFF WIP to `feat/bff-session-layer`.
2. Merge `origin/dev` (at `69c7cfc`) into `dev`; **review the identity backend diff after the merge - do not blind-`-X theirs`** (it can silently drop a security fix or clobber `.env`/keys); keep our web files.
3. Adapt BFF to new contract: `/api/auth/login` reads `data.mfa_token` → `mfaToken`; `/api/auth/mfa/verify` sends `{mfa_token, code}` + tenant slug.
4. Apply migration `0007`; re-seed DB (backup before re-seed).
5. Verify: ruff + full backend pytest (incl. `test_mfa_challenge.py`) + web tsc/eslint/build.

### Phase 0.5 - Infra & routing
- Hosts: `127.0.0.1 web.localhost`, `signup.localhost`, `tester.localhost`, `tester.signin.localhost` (+ dev slugs); `allowedDevOrigins` wildcards.
- **Host allowlist** implemented in the BFF + middleware + reverse proxy (unknown hosts → 444) - see security review.
- `resolveTenantSlug` + `getTenantSlug` regex, **no acme fallback, no env fallback in prod posture** (dev-only opt-in documented).
- Delete `/api/v1` rewrite; point all client calls through BFF. Add security headers config (posture #7 incl. Turnstile CSP).

### Phase 1 - Backend (`services/identity`)
- `signup_verify_code`: new → `onboarding` + token; existing → `status:"unavailable"`.
- Keep `signup_set_password` (owner password set **before** org - gate at `service.py:511`); keep password auth; login = `POST /auth/login` + PR #47 `POST /auth/mfa/verify` (no new passwordless-login endpoint).
- `signup_create_organization`: create tenant; return owner session/tokens (MFA is mandatory for every account - no tenant-level opt-out flag).
- **Server-side password strength** for owner + member (Medium).
- Invite: `InvitationAcceptRequest` drops `email` (server derives), password min 12; `accept_invitation` returns session tokens (MFA-pending); new `POST /invitations/resolve` (rate-limited, generic errors); `send_invitation` → fragment link + `SIGNUP_BASE_URL` setting; role from stored invite; TTL + single-use + revoke-on-change.
- New `POST /auth/handoff` (single-use via `GETDEL`, 120s, tenant-bound, destination embedded, SKIP_AUTH_PATHS, Redis store mirroring `MfaChallengeStore`); redemption rate-limited.
- **Access-token revocation (High):** `sid` claim on access JWTs; `get_current_user` checks session status; revoke token family on logout, password change, MFA disable, MFA reset.
- Owner-only `GET /sessions/tenant` (all users' IP/device/last-active) + revoke; refresh `last_active_at` on token refresh; **IPs/devices treated as PII** (owner + `sessions:read` only, no token hashes exposed, audited, IPs redacted in logs).
- `users/me/access` → `{roles, permissions}`; add `agents:read` + `intelligence:read` to catalog + member role.
- **Step-up re-auth endpoints** for MFA disable / email change / revoke-all (Medium).
- Tests for all of the above.

### Phase 2 - Register (`web.localhost` + `signup.localhost`)
- Marketing: remove all Log in links/CTAs; register-only → `signup.localhost/signup`; remove demo copy (`policy-dialog.tsx:57`).
- `signup.localhost/signup`: email + Turnstile gate; silent OTP; "unavailable" on existing email; wizard: plan → set password → org → `/setup-mfa` → handoff.
- New BFF: `/api/auth/code/send`, `/api/auth/code/verify`, `/api/auth/org`, `/api/auth/handoff/mint` - all `no-store`, origin-checked, rate-limited.

### Phase 3 - Login (`{slug}.signin.localhost`)
- `TenantLoginForm`: email + password → inline MFA (`mfa_token`) → handoff; `mfa.setup` → `/setup-mfa`; reset-password on the signin subdomain.
- BFF: adapt `/api/auth/login` + `/api/auth/mfa/verify`; add `/api/auth/handoff` (tenant origin: Host+tenant check → cookie → 307 → `/dashboard`).
- **Reset-password flow (High):** fragment + POST token, single-use, MFA survives reset, all sessions revoked, re-login requires MFA.
- **Unknown-tenant generic page** (Medium).

### Phase 4 - Workspace (`{slug}.localhost/dashboard`)
- Session carries roles/permissions; sidebar filters: Agents (`agents:read`), ERP (`erp.*`), Intelligence (`intelligence:read`), Members (`users:read`), Settings (`settings:read`); owner (`*`) sees all + owner-only **Sessions & Devices** page (all users' IP, device, last-logged, revoke - PII-protected, audited); Members page for invites.
- All dashboard APIs enforce permissions **server-side** (sidebar filtering is UI only).

### Phase 5 - Verify end-to-end
- ruff + pytest; migration + re-seed; web tsc/eslint/build.
- Browser E2E: owner signup → dashboard URL `tester.localhost/dashboard` (no `signin`); member invite → accept (name/password/confirm) → QR → dashboard; login at `tester.signin.localhost/signin`; existing-email "unavailable"; `/api/v1` unreachable from browser; no acme fallback anywhere.
- **Security acceptance checklist:**
  - Logout + password change + MFA disable → existing access tokens immediately rejected (revocation).
  - Handoff: wrong-tenant Host rejected; replay of a consumed token rejected; >120s old token rejected; redirect target only from token.
  - Auth pages/BFF responses return `Cache-Control: no-store`.
  - Unknown `Host` rejected by BFF/middleware/proxy.
  - Password reset leaves MFA enabled and revokes sessions.
  - No tokens/emails in query strings or server logs; invite/backup-code storage hash-only.

## Open items (confirm before execution)

- **Email delivery for OTP + invite links in dev (confirmed).** Dev uses `LogEmailService` - OTP codes are logged, and `SIGNUP_BASE_URL` builds `signup.localhost/invite#t=...` for invite links. No real mail server needed in dev.
- **Default dev test tenant slug: `tester`** (already in the dev DB as `Tester Technologies` + `test@gmail.com`) with hosts `tester.localhost` + `tester.signin.localhost`. Integration tests use `olympus` as a fixture-only tenant - do not seed it into dev.

## Related

- ADR-004 (login security posture - anti-enumeration + rate limiting)
- `SECURITY.md` (vulnerability reporting + deployment best practices)
- SKY-20 (MFA feature), SKY-21 (recovery guidance from account-level state), SKY-24 (security checklist)
