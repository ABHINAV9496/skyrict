# ADR-003: Staging environment - wildcard DNS + wildcard TLS via cert-manager DNS-01

## Status

Accepted

## Date

2026-08-04

## Context

The multi-tenant routing model (tenant slug derived from the request subdomain)
was established locally in SKY-12 (`*.localhost` via nginx). Security-critical
integrations - tenant isolation, real certificate validation, external-network
behavior - cannot be verified locally: DNS, TLS, and edge-network failures only
surface on a real, internet-reachable environment.

Until now there was no staging environment at all: the `cd-staging.yml` (and
`cd-production.yml`) workflows were commented-out stubs with
`# TODO: Add kubectl/terraform deploy commands`, and `infra/terraform/` was an
empty skeleton. SKY-24 (isolation suite against staging) and SKY-29 (demo
readiness) both depend on a reachable staging identity service.

This ADR records the infrastructure decisions for the staging environment.

## Decision

### 1. Staging domain and DNS

- Staging tenants live under **`*.staging.skyrict.com`**; the test subdomain
  used for acceptance is `acme-test.staging.skyrict.com`.
- A dedicated Route 53 hosted zone **`staging.skyrict.com`** is managed by
  Terraform (`infra/terraform/environments/staging/`), delegated from the
  parent `skyrict.com` zone once during bootstrap.
- Terraform creates the wildcard record `*.staging.skyrict.com` pointing at the
  identity ingress load balancer (A record for an IP, CNAME for a hostname -
  the CD pipeline resolves the address from the cluster).

### 2. Wildcard TLS

- **cert-manager** issues and **auto-renews** a wildcard certificate for
  `*.staging.skyrict.com` (+ the zone apex) using the **Let's Encrypt
  production CA** and the **DNS-01** challenge against Route 53.
- DNS-01 (rather than HTTP-01) is chosen because a wildcard certificate cannot
  be issued over HTTP-01, and it avoids opening inbound ports for challenges.
- The `ClusterIssuer` reads Route 53 credentials from a Kubernetes secret that
  the CD pipeline creates from GitHub secrets - credentials are never committed
  and never appear in manifests.
- The ClusterIssuer's `dnsZones` selector limits it to `staging.skyrict.com`
  (least privilege).

### 3. Deployment pipeline

- `cd-staging.yml` (GitHub Actions, `staging` environment) is the sole deploy
  path: build + push the identity image to GHCR (mutable `staging` tag and
  immutable `:sha` tag) → `kubectl apply -k` of the staging overlay → pin the
  deployed image to `:sha` → Terraform applies the wildcard DNS record → verify
  `https://acme-test.staging.skyrict.com/health` returns 200 with a valid
  certificate from the GitHub runner (an external network).
- Cluster access via a base64-encoded kubeconfig in the `KUBE_CONFIG_STAGING`
  GitHub secret; AWS credentials via GitHub secrets (shared by Terraform and
  the cert-manager secret).

### 4. Cloud-agnostic structure

- AWS-specific resources live only in `infra/terraform/modules/dns/route53/`,
  behind a documented DNS module contract (`modules/dns/README.md`). Another
  provider (e.g. Cloudflare) can be added as a sibling module and selected with
  a one-line change in the environment - no environment glue is provider-aware.
- Kubernetes manifests keep every staging value inside
  `infra/k8s/overlays/staging/`; nothing staging-related is hardcoded outside
  the overlay.

## Consequences

### Positive

- A real, internet-reachable staging environment validates DNS, TLS, and
  edge-network behavior before production; the CD pipeline's verify step
  enforces the acceptance criteria on every deploy.
- Wildcard TLS is fully automated (issue + renewal), no manual certificate
  rotation.
- Tenant subdomains behave identically to the intended production contract
  (`Host`-derived `X-Tenant-Slug` resolution in the identity service).
- Provider-agnostic Terraform keeps the door open for non-AWS infrastructure
  with minimal churn.

### Negative

- Route 53 write credentials are stored in the staging cluster (cert-manager
  secret). Mitigated by least-privilege scoping (`dnsZones` selector + a
  dedicated IAM policy documented in the runbook).
- The first bootstrap is manual and ordered (cluster prerequisites, secrets,
  zone creation + delegation, then the CD pipeline) - documented in
  `docs/runbooks/staging-deployment.md`.
- Staging and production share one wildcard domain shape; production will need
  its own zone/certificates in a later ticket.

## References

- SKY-12 (local subdomain routing model)
- `infra/terraform/environments/staging/` + `infra/terraform/modules/dns/`
- `infra/k8s/overlays/staging/`
- `.github/workflows/cd-staging.yml`
- `docs/runbooks/staging-deployment.md`
