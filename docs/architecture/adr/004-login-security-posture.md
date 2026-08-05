# ADR-004: Login security posture — anti-enumeration and rate limiting

## Status

Accepted

## Date

2026-08-05

## Context

The security checklist sign-off ([AUTH-TASK-055], Jira SKY-24) audited the
identity service's login surface and found two gaps:

1. **Email enumeration at the API level.** `POST /auth/login` raised distinct
   errors per failure mode: `UserNotFoundError` (404), `UserDisabledError`
   (403), `EmailNotVerifiedError` (403), and `InvalidPasswordError` (401).
   A caller could therefore learn whether an email is registered, disabled, or
   unverified purely from the HTTP status code and problem-type URI — an
   account-existence oracle that enables targeted phishing and account
   enumeration at scale.
2. **No rate limiting on `POST /auth/login`.** The endpoint was the only
   abuse-prone auth route without the Redis fixed-window limiter (registration
   had it), leaving brute-force and credential-stuffing unmitigated on the
   highest-value endpoint.

## Decision

### Uniform login failure response

Every login failure — unknown email, wrong password, disabled account,
unverified account — raises the **same** `AuthenticationError` with the same
message (`"Invalid email or password."`), mapped by the existing handler to a
single 401 `authentication-error` problem+json response. No failure branch
produces a different status code, problem type, or detail.

To close the timing side-channel (a known account with a wrong password costs
one Argon2id verification; an unknown email costs only a DB lookup — a
measurable difference), every attempt performs exactly one Argon2id
verification:

- unknown email → verify against a fixed dummy hash (same cost, always false);
- known account → verify the real hash first, then evaluate account state.

Failed logins are audited as `auth.login.failed` (target `email:<address>`
when no user row exists, `user:<id>` otherwise) so brute-force and
credential-stuffing are visible to security monitoring.

The frontend guides recovery (e.g. "verify your email", "reset your password")
from account-level state (SKY-21), never from backend error semantics.

### Login rate limiting

`POST /auth/login` is rate-limited with the existing Redis fixed-window
limiter (fail-open on infra errors), keyed per `(source IP, account)` —
`RATE_LIMIT_LOGIN` (5) attempts per `RATE_LIMIT_WINDOW_SECONDS` (300) per
`ip:email`. Including the source IP means an attacker cannot exhaust a
victim's quota from the victim's own IP (no account-lockout DoS); including
the email means a shared NAT IP does not lock out every tenant behind it.

## Alternatives considered

- **Distinct statuses by failure stage (status quo).** Rejected: it is the
  enumeration oracle the checklist flagged.
- **Uniform 403 for all failures.** Rejected: 401 is the correct semantic for
  unauthenticated credential failures and matches the token-error family.
- **Email-only rate-limit key.** Rejected: enables account-lockout DoS.
- **IP-only rate-limit key.** Rejected: penalizes shared/NAT IPs and still
  allows cross-account stuffing from one IP until a higher threshold.

## Consequences

### Positive

- No account-existence oracle via status code, problem type, detail, or
  response time.
- Brute-force / credential-stuffing is rate-limited and audited end-to-end.
- Uniform contract is simple for clients and testable as an invariant.

### Negative

- Legitimate users get the same message for "wrong password" and "email not
  verified"; recovery guidance must come from the frontend (SKY-21).
- Failed-login audit rows grow with attack traffic (acceptable; they are the
  point of the event and are retained per audit policy).

### Risks

- The dummy-hash timing equalization assumes the DB lookup is fast relative to
  Argon2id; if the repository path ever changes cost characteristics, the
  timing assumption must be re-verified.

## Related

- [AUTH-TASK-055] security checklist (SKY-24)
- SKY-20 (MFA feature) — tenant-owner MFA enforcement flag (`mfa_required`)
  is emitted at login; the `/auth/mfa/verify` challenge endpoint remains
  blocked on SKY-20.
- SKY-13 (staging CD) — the tenant-isolation suite runs against local/CI
  Postgres; the staging run is blocked until staging CD is enabled.
