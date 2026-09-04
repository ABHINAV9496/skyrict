# Terraform - Skyrict infrastructure

Cloud infrastructure as code. Environments are thin glue layers; provider
implementation lives in reusable modules.

## Layout

```
infra/terraform/
├── modules/
│   ├── dns/                 # DNS module contract + provider implementations
│   │   ├── README.md        # the provider-neutral contract
│   │   └── route53/         # AWS Route 53 implementation
│   └── (future modules…)
└── environments/
    ├── dev/                 # placeholder
    ├── staging/             # wildcard DNS for *.staging.skyrict.com
    └── production/          # placeholder (separate ticket)
```

## Staging environment

`environments/staging/` manages the Route 53 hosted zone for
`staging.skyrict.com` and the wildcard record `*.staging.skyrict.com` that
points tenant subdomains at the identity service ingress load balancer.

- Remote state: S3 + DynamoDB locking, injected with `-backend-config` from
  GitHub secrets (see `backend.tf` and `docs/runbooks/staging-deployment.md`).
- The wildcard target is the ingress load balancer address: an IPv4 address
  becomes an `A` record, a hostname becomes a `CNAME`.
- TLS certificates are intentionally **not** provisioned here - cert-manager
  issues and renews the wildcard certificate in-cluster (DNS-01), writing its
  `_acme-challenge` TXT records into this same zone.

## Adding another DNS provider

1. Add `modules/dns/<provider>/` implementing the contract in
   `modules/dns/README.md` (same variables/outputs as `route53/`).
2. In `environments/<env>/main.tf`, change the module `source`; add the
   provider's `required_providers` + config in `provider.tf`.
3. Nothing else changes - the environment glue is provider-agnostic.

## Validation (no credentials required)

```bash
terraform fmt -check -recursive infra/terraform/
cd infra/terraform/environments/staging
terraform init -backend=false && terraform validate
```

CI enforces this on every infra PR (`.github/workflows/ci-infra.yml`).
