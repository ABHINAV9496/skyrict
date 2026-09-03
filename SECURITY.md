# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.x     | Active development |

## Reporting a Vulnerability

If you discover a security vulnerability within Skyrict, please send an email to **security@skyrict.dev**. Do **not** open a public GitHub issue for security vulnerabilities.

We will acknowledge receipt within 48 hours and aim to provide a resolution timeline within 7 business days.

### What to include

- Description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Affected version(s)
- Any suggested fix (if applicable)

### What to expect

- **Acknowledgment** - within 48 hours of your report
- **Triage** - severity assessment and initial investigation within 7 business days
- **Fix timeline** - communicated once triage is complete
- **Disclosure** - coordinated disclosure after a fix is available. We request 90 days maximum before public disclosure.

### Scope

In scope:
- Authentication and authorization bypasses
- SQL injection, XSS, CSRF, or other injection attacks
- Privilege escalation (including agent guardrail bypasses)
- Data exposure through API endpoints
- Multi-tenancy data leakage
- Cryptographic weaknesses in data-at-rest or in-transit
- Denial of service vectors

Out of scope:
- Social engineering attacks
- Third-party dependency vulnerabilities (report upstream)
- Issues requiring physical access to infrastructure
- UI/UX issues that do not have a security impact

### Recognition

Security researchers who report valid vulnerabilities will be credited in the release notes (unless anonymity is requested). We do not offer bug bounties at this stage but welcome ongoing collaboration.

## Security Best Practices for Deployment

- Never deploy with default secrets. Generate unique keys for every environment.
- Enable TLS termination at the load balancer or reverse proxy.
- Use environment variables or a secrets manager (Vault, AWS Secrets Manager) - never commit secrets to source control.
- Enable database row-level security (RLS) for multi-tenant deployments.
- Restrict Kafka broker access to internal networks only.
- Rotate API keys and JWT signing keys on a regular schedule.
- Enable audit logging in production. Agent actions must be fully traceable.
