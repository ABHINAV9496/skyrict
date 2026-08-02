# Identity Service

Authentication, authorization, multi-tenancy, sessions, and audit for Skyrict.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/login` | Authenticate with email/password |
| POST | `/api/v1/auth/register` | Register a new account |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Revoke session |
| POST | `/api/v1/auth/introspect` | Inspect a token |
| GET | `/api/v1/users/me` | Get current user profile |
| PUT | `/api/v1/users/me` | Update profile |
| POST | `/api/v1/users/me/password` | Change password |
| GET | `/api/v1/organizations/me` | Get current org |
| POST | `/api/v1/organizations` | Create org |
| GET | `/api/v1/sessions` | List active sessions |
| DELETE | `/api/v1/sessions/{id}` | Revoke session |
| DELETE | `/api/v1/sessions` | Revoke all sessions |
| POST | `/api/v1/mfa/setup` | Initiate MFA setup |
| POST | `/api/v1/mfa/verify` | Verify MFA code |
| POST | `/api/v1/passkeys/register/start` | Start passkey registration |
| POST | `/api/v1/sso/oidc/start` | Start OIDC SSO |
| GET | `/api/v1/health` | Liveness probe |
| GET | `/api/v1/ready` | Readiness probe |

## Local Development

```bash
# From repo root
make dev

# Or directly
uv run --directory services/identity identity serve --reload
```

## Local Multi-Tenant Testing

Tenant resolution in production is subdomain-driven: `acme.skyrict.com`
reaches the service with an `X-Tenant-Slug: acme` header injected by the
ingress. The dev stack reproduces that contract locally with nginx — the
application receives the same header either way.

```bash
# Boot the full stack (Postgres, Redis, identity service, nginx)
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d

# Two fake tenant subdomains, no DNS setup required (*.localhost -> 127.0.0.1)
curl -s http://acme.localhost/api/v1/health     # X-Tenant-Slug: acme
curl -s http://globex.localhost/api/v1/health   # X-Tenant-Slug: globex

# Path-based fallback when wildcard DNS is unavailable
curl -s http://localhost/acme/api/v1/health     # -> /api/v1/health + X-Tenant-Slug: acme
curl -s -X POST http://localhost/globex/login   # -> /api/v1/auth/login + X-Tenant-Slug: globex
```

Routing is defined in `infra/nginx/dev.conf` (mounted into the `nginx`
service). If port 80 is in use, set `NGINX_PORT=8080` in `infra/docker/.env`
(or export it in your shell) and use `http://acme.localhost:8080/...`.

## Running Tests

```bash
# Unit tests (no DB needed)
uv run pytest services/identity/tests/unit/ -v

# Integration tests (requires Docker)
uv run pytest services/identity/tests/integration/ -v
```

## Environment Variables

See `.env.example` for all required variables. Prefix: `IDENTITY_`
