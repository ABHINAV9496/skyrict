# Skyrict Identity Service - Project Overview

A beginner-friendly, complete guide to what was built, how it works, which files do what, and why it all matters.

> **Read this if:** you want to understand the Identity service end-to-end - from a brand-new user creating an account, to every locked-down API request behind it.

---

## 1. What this project is

**Skyrict Identity** is the **login / account / access-control service** for the Skyrict platform. It is a **multi-tenant** system: many different organizations (tenants) share one codebase and one database, but each organization can only ever see its own users, roles, and data.

This work completed three security features:

| Feature | Ticket | Plain meaning |
|---|---|---|
| **RBAC** | AUTH-TASK-030 | Role-based access control - you can only do what your role allows |
| **Role builder** | AUTH-TASK-032 | Admins can create their own custom roles from a fixed menu of permissions |
| **MFA** | AUTH-TASK-035 | Multi-factor authentication - TOTP app codes + single-use backup codes |

**Tech stack:** Python · FastAPI · PostgreSQL · Redis · SQLAlchemy (async) · PyJWT (RS256) · Argon2id (passwords) · pyotp (TOTP) · Fernet (secret encryption) · Docker · Postman/Newman (manual testing).

---

## 2. Big picture - how the pieces fit together

```
        FRONTEND (Next.js)  /  Postman Runner
                 │  HTTP request + "X-Tenant-Slug" header + "Bearer <token>"
                 ▼
┌────────────────────────────  IDENTITY SERVICE (FastAPI)  ────────────────────────────┐
│                                                                                       │
│  MIDDLEWARE ─►  TenantContext: resolves which organization this request belongs to    │
│                 RateLimiter (Redis): throttles login/register so bots can't brute-force│
│                                                                                       │
│  ROUTERS ─►  auth · mfa · roles · /permissions · organizations(+settings) · users     │
│              sessions · invitations · health/ready          (all under /api/v1)        │
│                 │                                                                     │
│                 ▼  every protected route depends on these                             │
│  api/deps.py ─►  ① verify JWT → 401    ② tenant match → 404                           │
│                  ③ MFA gate → 403      ④ RBAC permission → 403                       │
│                 │                                                                     │
│                 ▼                                                                     │
│  FEATURE SERVICES ─► the business rules (login, MFA, roles, invites, tokens...)       │
│                 │                                                                     │
│                 ▼                                                                     │
│  REPOSITORIES ─► talk to the database (one per feature)                               │
└───────────────────────────────┬───────────────────────────────────────────────────────┘
                                ▼
              ┌─────────────────────┐          ┌─────────────────────┐
              │   PostgreSQL        │          │   Redis             │
              │  users · tenants    │          │  rate-limit counters│
              │  roles · sessions   │          └─────────────────────┘
              │  invitations · audit│
              └─────────────────────┘
```

**Rule of thumb for every feature:** `router` (HTTP in/out) → `service` (rules) → `repository` (data). The router never touches the database directly, and the service never sees an HTTP request. This keeps the code clean and testable.

---

## 3. How a single request works (the security pipeline)

Every protected request must pass **four gates**, in order. Failing any gate stops the request immediately.

```
  Request ──► ① verify JWT ──► ② tenant match ──► ③ MFA gate ──► ④ RBAC check ──► handler
              (is the token     (token's tenant    (MFA forced     (has the right
               real + valid?)    == slug's tenant?)  but not done?)   permission?)
               fail → 401          fail → 404         fail → 403       fail → 403
```

| Gate | Returns | Example test |
|---|---|---|
| ① No/invalid/expired token | **401** | 030.8 (GET /roles with no token) |
| ② Token from another tenant | **404** | 030.9 (wrong tenant slug) |
| ③ MFA mandatory but not enrolled | **403** | 035.3 (GET /users/me before MFA) |
| ④ Missing permission key | **403** | 030.7 (member tries POST /roles) |

> **Why 404 for wrong tenant?** If you could get a 403, you'd learn "this other tenant exists". 404 hides that entirely - one more layer of isolation.

---

## 4. The full user journey - from zero to fully secured

### Stage 1 - Register an organization + owner (S1)

The very first step. A person signs up with their organization's name and their own credentials.

```
  POST /auth/register  { organization_name, email, password, full_name }
     │
     ├─ 1. Make a unique "slug" from the org name:  "Acme Corp" → "acme-corp"
     │        (if taken → "acme-corp-2", "-3", …; reserved names like "admin" are blocked)
     │
     ├─ 2. CREATE a tenant row        (the organization's private space)
     │
     ├─ 3. CREATE 5 built-in roles for that tenant:
     │        tenant_owner        → can do EVERYTHING ("*")
     │        organization_admin  → manage users/roles/settings/billing
     │        department_manager  → read users/roles + approve ERP purchases
     │        standard_user       → basic read-only
     │        auditor             → see audit logs & sessions
     │
     ├─ 4. CREATE the owner user with an Argon2id password hash
     │        (one-way, salted, slow - a leaked hash is useless to an attacker)
     │
     ├─ 5. GRANT the "tenant_owner" role to this user
     │
     ├─ 6. Log to the audit trail: "auth.register.success"
     │
     └─ 7. Email a verification link (token shown in dev/test only)
```

**What the user gave:** org name, email, password, full name.
**What the system made for them:** tenant ID + slug, user ID, 5 roles, Argon2id hash, verification token.

> Important: the account is **not verified yet**, and no login tokens are issued. That happens next.

### Stage 2 - Verify the email (S2)

```
  POST verify { token }
     ├─ verify_jwt: signature + expiry + must be an "email_verify" token
     └─ mark user.is_verified = true   (idempotent - safe to retry)

  Until verified: login is BLOCKED (prevents fake-email signups)
```

### Stage 3 - First login - owner is forced to set up MFA (S3)

```
  POST /auth/login { email, password }
     ├─ find user (scoped to the tenant)     ── not found → generic "invalid email or password"
     ├─ account active?  email verified?     ── same generic message (no account-existence oracle)
     ├─ verify password (Argon2id)
     ├─ load the user's roles  →  is this person a tenant_owner?
     ├─ tenant policy: mfa_required_for_all_members = on/off?
     │
     │   mfa_is_required():
     │     owner + no MFA  ──────────────────────►  MFA REQUIRED  (no skip path)
     │     member + policy ON  ──────────────────►  MFA REQUIRED
     │     member + policy OFF ──────────────────►  not required (free pass)
     │
     └─ issue a token pair anyway + create a session + security email if new device
        Response: { access_token, refresh_token, mfa_required=true, next_step="mfa.setup" }
```

**Clever bit:** the token IS issued - but the **MFA gate** (gate ③) blocks every other endpoint with 403 until MFA is done. So the owner literally cannot skip it.

### Stage 4 - MFA setup (S4)

```
  POST /mfa/setup   (this endpoint is EXEMPT from the MFA gate so enrollment can finish)
     ├─ generate TOTP secret  (pyotp.random_base32())
     ├─ build the otpauth://… QR URL for the authenticator app
     ├─ generate 10 backup codes  (64 bits of randomness each)
     │
     └─ STORE SECURELY:
          users.mfa_secret        = Fernet-encrypted        (safe even if DB leaks)
          users.mfa_backup_codes  = Argon2id-hashed × 10     (safe even if DB leaks)

  Response (shown ONCE): { secret, provisioning_uri, backup_codes[10] }
```

### Stage 5 - Verify the first code (S5)

```
  POST /mfa/verify { code }
     ├─ try TOTP:   pyotp.verify(code, valid_window=1)   ← tolerates ~30s clock skew
     ├─ or backup code: find matching hash → verify → set that slot to "None"  (SINGLE-USE)
     └─ on match: users.mfa_enabled = true   +   audit "mfa.enabled"

  Reusing a backup code later → 403  (test 035.15 proves this)
```

### Stage 6 - Re-login, now enrolled (S6)

```
  login → mfa_is_required = False  →  mfa_required=false, next_step=null
  Token now unlocks EVERY route   (GET /users/me → 200)
```

### Stage 7–9 - Adding a member (S7, S8, S9)

```
 S7  Owner invites:  POST /invitations { email, role }
     └─ token = 32 random bytes, expires in 7 days, sent by email

 S8  Member accepts: POST /invitations/accept { token, email, password, full_name }
     ├─ validate: token exists · not expired · not used · email matches the invite
     ├─ create user  (verified immediately - no email step needed)
     ├─ grant the default invite role ("viewer") if it exists
     └─ mark invitation used

 S9  Member logs in
     ├─ policy OFF ──► mfa_required=false   (member not forced - test 035.8)
     └─ policy ON  ──► mfa_required=true    → 403 gate until member enrolls (035.2→035.6)
```

### Stage 10 - Every request afterwards

Back to **section 3**: 401 → 404 → 403(MFA) → 403(RBAC) → handler → service → repository → database.

---

## 5. Database tables (the data model)

```
 tenants:   id · name · slug(unique)
            mfa_required_for_all_members  ← NEW (tenant MFA policy)

 users:     id · tenant_id ──────────────► belongs to one tenant
            email · password_hash (Argon2id)
            is_verified · is_active
            mfa_enabled  mfa_secret (Fernet)  mfa_backup_codes (10 hashes)  ← NEW

 roles:     id · tenant_id · name · permissions[list of keys] · is_system_role
            (e.g. tenant_owner → ["*"])

 user_roles: user_id · role_id · tenant_id · scope_type · scope_id
            (join table - a user can have several roles)

 sessions:  id · user_id · refresh_token_hash · expires_at · is_active

 invitations: id · tenant_id · email · token · expires_at · used_at

 audit_log:  action · target · user_id · tenant_id · ip · user_agent · details
```

```
        tenants ◄──────┐
          │            │ (tenant_id)
          ├── users    │
          ├── roles ◄──┴── user_roles ──► users
          ├── invitations ──► creates a user
          └── audit_log  (references users/tenants loosely)
        sessions ──► users
```

**Migration:** `0005_mfa_enforcement.py` adds the MFA columns (`users.mfa_enabled`, `users.mfa_secret`, `users.mfa_backup_codes`, `tenants.mfa_required_for_all_members`).

---

## 6. File-by-file guide (simple words)

### 6.1 Core - the shared security foundation

| File | What it does | Why it matters |
|---|---|---|
| `src/identity/core/config.py` | Loads all settings from env vars; validates them | New `MFA_ENCRYPTION_KEY` (must be a valid Fernet key) + "production safety" guards that refuse to boot with `DEBUG=true`, wildcard CORS, missing domain, or committed test keys |
| `src/identity/core/security.py` | The "safe" of the whole service: JWT sign/verify (RS256), Argon2id password hashing, Fernet MFA-secret encryption, and the `mfa_is_required()` rule | Single verification path → no accidental weak spots; MFA secrets are unreadable in the DB; the "who is forced to enroll" rule lives here so login and the request gate can never disagree |
| `src/identity/core/permissions.py` | The fixed menu of permission keys (`users:write`, `erp.invoice.approve`, … = 19 keys, 10 groups) | The **only** source of truth for what permissions exist - custom roles can't invent keys |
| `src/identity/core/constants.py` | Magic values: system role definitions, reserved slugs/emails, token expiries, problem-type URIs | One place to change a default without hunting through code |

### 6.2 API layer - the doors into the service

| File | What it does | Why it matters |
|---|---|---|
| `src/identity/api/deps.py` | Dependency injection: `get_current_user` (JWT + tenant + MFA gate), `require_permission(...)` (RBAC gate), all repository/service factories | **One place** enforces auth/MFA/RBAC on every route - a new endpoint is secure by default |
| `src/identity/api/readiness.py` | Startup check: database, Redis, JWT keys, MFA key | Fails fast at boot instead of breaking in production |
| `src/identity/api/v1/router.py` | Wires every feature's router into `/api/v1` | The single "directory" of all endpoints |

### 6.3 Features - the business logic

**auth/** (login, register, email verify, tokens)
| File | What it does | Why it matters |
|---|---|---|
| `service.py` | `AuthenticationService.login` (checks password, computes `mfa_required`/`next_step`), `register` (creates tenant + 5 roles + owner), `verify_email`; `TokenService` (create/refresh/revoke tokens) | The heart of the whole flow - every user journey starts here; refresh-token **rotation + reuse detection** kills stolen tokens |
| `schemas.py` | The login/register request & response shapes | Adds `mfa_required`/`next_step` to the login response contract |

**mfa/** (the new feature)
| File | What it does | Why it matters |
|---|---|---|
| `router.py` | `POST /mfa/setup`, `/verify`, `/disable`, `/reset` | The four MFA endpoints (disable needs your password; reset needs owner + `mfa:manage`) |
| `service.py` | `setup_totp` (secret + QR + 10 backup codes), `verify_totp` (pyotp, clock-skew tolerant), `redeem_backup_code` (single-use), `enable_mfa`, `disable_mfa`, `reset_mfa_by_owner` | Everything security-critical about MFA; backup codes hashed with the **same Argon2id function** at generation and redemption (a DoD requirement) |
| `schemas.py` | Setup/verify response schemas | Returns `secret`, `provisioning_uri`, `backup_codes` (shown once) |

**roles/** (RBAC + role builder)
| File | What it does | Why it matters |
|---|---|---|
| `router.py` | `GET /permissions` (catalog), `POST/GET/PATCH/DELETE /roles`, `POST /roles/{id}/assign` | The role-builder + RBAC API; strict validation returns 422 for unknown keys / duplicate / reserved names |
| `service.py` | `AuthorizationService.check_permission` (fail-closed RBAC), `RoleManagementService` (create/list/get/update/delete/assign, system-role protection) | Where access decisions are actually made; defaults to **deny** |
| `repository.py` | Role queries + grants; explicit `delete(user_role)` on role delete | Fixes the 500 that used to happen when deleting a role that had members |

**organizations/** (tenant + MFA policy)
| File | What it does | Why it matters |
|---|---|---|
| `router.py` | `GET /organizations/me`, `POST /organizations`, and `PATCH /tenants/{id}/settings` | The settings endpoint (requires `tenants:write`) is how an owner flips `mfa_required_for_all_members` on/off |
| `service.py` / `repository.py` / `schemas.py` / `ports.py` | Tenant logic + settings update | Carries the MFA policy down to the database |

**users/** (user data support)
| `ports.py` / `repository.py` | User queries + `update_mfa`/`disable_mfa` | Persists MFA state and serves the MFA gate's lookups |

**invitations/** (adding members)
| `service.py` | `create_invitation` (7-day token) + `accept_invitation` (validates token, creates verified user, grants default role) | The safe, audited way to grow a tenant |

### 6.4 Models + migration

| File | What it does |
|---|---|
| `models/user.py` | SQLAlchemy User model + new `mfa_enabled`, `mfa_secret`, `mfa_backup_codes` |
| `models/tenant.py` | Tenant model + new `mfa_required_for_all_members` |
| `domain/entities.py` | Plain-Python domain objects (User, Tenant, Role) - models map to these |
| `alembic/versions/0005_mfa_enforcement.py` | Schema migration adding the MFA columns |

### 6.5 Tests

| File | What it proves |
|---|---|
| `tests/unit/features/test_mfa_service.py` | TOTP + backup-code unit tests - including the DoD test that generation and redemption use **one identical hashing function** |
| `tests/integration/api/test_mfa.py` | End-to-end MFA: owner forced, policy forces members, gate blocks, backup code single-use, owner reset |
| `tests/integration/api/mfa_helpers.py` | `enroll_mfa_if_required` helper used by many tests |
| `tests/unit/features/test_permissions_api.py`, `test_auth_service.py` | Catalog + login posture coverage |
| `tests/conftest.py` | Test setup: fresh temp RSA keys, `IDENTITY_DEBUG=false` - makes tests hermetic (the 4 "failed" tests now pass) |

### 6.6 Infra / packaging

| File | What it does |
|---|---|
| `pyproject.toml` + `uv.lock` | Dependencies - added `pyotp` and `argon2-cffi` for MFA |
| `.env.example` | Documents the new env vars (`IDENTITY_MFA_ENCRYPTION_KEY`, …) |

### 6.7 Postman (the manual test deliverable)

`postman/` was an automated Postman collection (40 requests) that ran the whole flow: register → verify → owner MFA → invite member → role builder → RBAC → MFA policy → teardown. It was validated against the official Postman schema, ran **40/40 green**, was never committed to git, and has been **deleted** from the working tree as intended.

---

## 7. Why this matters in the real world

- **MFA is the single most effective control against credential theft.** Industry data shows MFA blocks the vast majority of automated account-takeover attacks. Passwords alone are not enough.
- **Protect the most powerful account first.** The tenant owner holds the keys to the whole organization, so their MFA is **mandatory with no skip path**.
- **Backup codes survive DB exposure.** Hashed with Argon2id and single-use, a leaked database doesn't allow replay or brute-force recovery.
- **Least privilege (RBAC).** Nobody gets more access than their job needs → a compromised account can only damage what its role allows (bounded blast radius).
- **Fail-closed authorization.** Unknown role, unknown permission, inactive user → **deny**. The dangerous opposite (fail-open) causes privilege escalation.
- **Multi-tenant isolation.** Permissions and data are scoped per tenant; wrong tenant → 404, so you can't even probe other organizations.
- **The permission catalog stops sprawl.** Only sanctioned permission keys exist, so custom roles can't escalate by typo.
- **Compliance.** SOC 2, PCI-DSS, GDPR, and NIST SP 800-63B all require or strongly encourage MFA, access control, encryption at rest, and audit trails - all present here.
- **Supporting hardening:** RS256-only JWTs (blocks `alg:none` / algorithm-confusion attacks), Argon2id passwords, Fernet-encrypted secrets, refresh-token rotation + reuse detection, rate limiting, audit logging on every sensitive action, and fail-fast startup verification.

---

## 8. How we proved it works

```
Unit tests:  256/256 passing   (docker exec … pytest tests/unit)
Postman run: 40/40 requests green (full flow, folders 00 → 04)
```

**To run the tests yourself:**
```bash
# inside the running identity container
docker exec -w /app/services/identity skyrict-identity \
  /app/.venv/bin/python -m pytest tests/unit -q -p no:cacheprovider
```

**To run the flow manually:** boot the stack (`docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d`), run the migration, then either use the Postman collection or hit the endpoints in order: register → verify → login (forced MFA) → mfa/setup → mfa/verify → login → invite → accept → member login → roles/permissions → teardown.

---

## Appendix - credentials & secrets cheat sheet

| Secret | Where it lives | Protected by |
|---|---|---|
| Password | `users.password_hash` | Argon2id (random salt, slow) |
| TOTP secret | `users.mfa_secret` | Fernet encryption at rest |
| Backup codes | `users.mfa_backup_codes` | Argon2id hashes, single-use |
| Access token | client | RS256 signature, 15-minute expiry |
| Refresh token | client + `sessions.refresh_token_hash` | sha256 hash + rotation + reuse detection |
| Invite token | `invitations.token` | 32 random bytes, 7-day expiry |
| MFA encryption key | env `IDENTITY_MFA_ENCRYPTION_KEY` | fail-fast startup validation |
