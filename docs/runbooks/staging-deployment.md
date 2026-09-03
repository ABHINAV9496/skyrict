# Runbook: Staging deployment - wildcard DNS + TLS + identity service

Staging is `*.staging.skyrict.com`, deployed to an existing Kubernetes cluster
by `.github/workflows/cd-staging.yml`. TLS is a Let's Encrypt wildcard
certificate issued by cert-manager (DNS-01, Route 53). DNS is managed by
Terraform in `infra/terraform/environments/staging/`.

Acceptance criteria (DoD for SKY-13):
`https://acme-test.staging.skyrict.com/health` returns **200** with a **valid
TLS certificate**, resolved from an external network.

---

## 1. Cluster prerequisites (one-time, manual)

1. A Kubernetes cluster (any provider - the manifests are provider-neutral).
2. **ingress-nginx** installed (the Ingress resources use
   `ingressClassName: nginx`):

   ```bash
   kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/cloud/deploy.yaml
   ```

   The load balancer it provisions is the target of the wildcard DNS record.
3. **cert-manager** installed:

   ```bash
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml
   ```

   cert-manager installs into the `cert-manager` namespace - the CD pipeline
   puts the Route 53 credentials secret there (required for `ClusterIssuer`s).

## 2. GitHub secrets (one-time, manual)

Set these on the **`staging` environment** (Settings → Environments → staging)
or as repository secrets:

| Secret | Purpose |
|--------|---------|
| `KUBE_CONFIG_STAGING` | base64-encoded kubeconfig for the staging cluster |
| `AWS_ACCESS_KEY_ID` | Route 53 write credentials (Terraform + cert-manager secret) |
| `AWS_SECRET_ACCESS_KEY` | Route 53 write credentials |
| `AWS_REGION` | e.g. `us-east-1` |
| `TF_STATE_BUCKET` | S3 bucket for Terraform remote state (see §3) |
| `TF_LOCK_TABLE` | DynamoDB table for Terraform state locking (see §3) |

> The AWS user/role only needs `route53:ChangeResourceRecordSets`,
> `route53:ListHostedZones`, and `route53:GetChange` on the
> `staging.skyrict.com` zone, plus S3/DynamoDB access for Terraform state.

> **Enabling automated deploys**: the `deploy`/`dns`/`verify` jobs of
> `cd-staging.yml` are inert until the repository **variable**
> `CD_STAGING_ENABLED` is set to `true` (Settings → Variables → Actions). Until
> then, `main` pushes only trigger the image build job, and the deploy chain
> can still be exercised on demand with `workflow_dispatch`. Set the variable
> only after every item in this runbook (secrets above, backend §3, zone §4,
> cluster secrets §5) is in place.

## 3. Terraform remote state backend (one-time, manual)

```bash
aws s3api create-bucket --bucket skyrict-tfstate-staging --region us-east-1
aws dynamodb create-table \
  --table-name skyrict-tf-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

(The bucket name is an example - use the same name in `TF_STATE_BUCKET`.)

## 4. DNS zone + delegation (first bootstrap only)

Create the hosted zone and get its nameservers:

```bash
cd infra/terraform/environments/staging
terraform init \
  -backend-config="bucket=$TF_STATE_BUCKET" \
  -backend-config="key=staging/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$TF_LOCK_TABLE"
terraform apply -var="create_zone=true" -var="wildcard_target="
terraform output nameservers
```

Then add the four NS records to the parent `skyrict.com` zone (at the
registrar / parent DNS provider). The zone must be resolvable before
cert-manager can complete DNS-01 challenges.

After delegation is live, set `create_zone = false` in
`terraform.tfvars` (or pass `-var="create_zone=false"`) - all later applies
look the zone up by name.

## 5. Cluster secrets (one-time, manual)

```bash
# Namespace + identity runtime secrets (REQUIRED values, never committed):
#   IDENTITY_DATABASE_URL  postgresql+asyncpg://... (staging Postgres)
#   IDENTITY_REDIS_URL     redis://... (staging Redis)
#   IDENTITY_JWT_PRIVATE_KEY_PATH / IDENTITY_JWT_PUBLIC_KEY_PATH
#     -> paths inside the container where the JWT keys are mounted. Provision
#        staging keys from a secret manager; NEVER reuse the dev/test fixtures.
#   IDENTITY_JWKS_ISSUER / IDENTITY_JWKS_AUDIENCE
#   IDENTITY_CORS_ORIGINS (explicit list - never '*')
kubectl create namespace skyrict-staging  # (the overlay also creates it)
kubectl create secret generic identity-secrets-staging \
  --namespace skyrict-staging \
  --from-literal=IDENTITY_DATABASE_URL=... \
  --from-literal=IDENTITY_REDIS_URL=... \
  --from-literal=IDENTITY_JWT_PRIVATE_KEY_PATH=... \
  --from-literal=IDENTITY_JWT_PUBLIC_KEY_PATH=... \
  --from-literal=IDENTITY_JWKS_ISSUER=... \
  --from-literal=IDENTITY_JWKS_AUDIENCE=... \
  --from-literal=IDENTITY_CORS_ORIGINS='["https://app.skyrict.com"]'
```

> `IDENTITY_BASE_DOMAIN`, `ENVIRONMENT`, `LOG_*` are already set in the
> deployment manifest - only the secret-required values above belong in the
> secret. The identity service **refuses to start** if any required value is
> missing (fail-fast config).

## 6. Run the pipeline

Push to `main` (or trigger `workflow_dispatch` on `cd-staging.yml`). The CD
pipeline builds the image, applies the overlay, reconciles DNS, waits for the
certificate, and asserts:

```bash
curl -fsS https://acme-test.staging.skyrict.com/health
# {"status":"healthy","service":"identity"}
```

The GitHub runner is an external network, so a green pipeline satisfies the
staging acceptance criteria.

### First-run ordering (why step 4 comes before 6)

1. Cluster + ingress-nginx + cert-manager (§1)
2. GitHub secrets (§2) + TF backend (§3)
3. Zone creation + NS delegation (§4)
4. Cluster secrets (§5)
5. CD pipeline (§6) - applies the overlay, cert-manager issues the wildcard
   cert (DNS-01 into the delegated zone), the DNS job points
   `*.staging.skyrict.com` at the ingress load balancer, verify checks the
   endpoint.

## 7. Day-2 operations

- **Manual redeploy of a previous image** (rollback):

  ```bash
  kubectl set image deployment/identity identity=ghcr.io/nkswalih/skyrict/identity:<previous-sha> -n skyrict-staging
  kubectl rollout status deployment/identity -n skyrict-staging
  ```

- **Certificate status / renewal**: cert-manager renews automatically (~2/3 of
  lifetime). Check:

  ```bash
  kubectl get certificate skyrict-staging-wildcard -n skyrict-staging
  kubectl describe certificate skyrict-staging-wildcard -n skyrict-staging
  ```

- **DNS drift**: re-run `terraform plan` in `infra/terraform/environments/staging`
  (with backend flags from §4) - the CD `dns` job does this on every deploy.

## 8. Troubleshooting

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| CD fails at "Wait for wildcard certificate" | DNS-01 challenge failed | `kubectl describe certificate -n skyrict-staging`; `kubectl logs -n cert-manager deploy/cert-manager`; confirm NS delegation (§4) and the `cert-manager-dns-credentials` secret |
| Pods stuck `ImagePullBackOff` | `skyrict-registry` secret missing/stale | `kubectl get secret skyrict-registry -n skyrict-staging`; re-run CD (it recreates the secret from `GITHUB_TOKEN`) |
| Pods `CreateContainerConfigError` | `identity-secrets-staging` missing a required key | `kubectl get secret identity-secrets-staging -n skyrict-staging -o jsonpath='{.data}'`; compare with §5 |
| Identity refuses to start | fail-fast config (missing `IDENTITY_BASE_DOMAIN`, debug on, bad CORS, fixture keys) | `kubectl logs deploy/identity -n skyrict-staging --previous` |
| `acme-test...` resolves to the wrong IP | DNS propagation / stale wildcard record | `getent hosts acme-test.staging.skyrict.com`; compare with the ingress LB address |
| `curl` reports an untrusted certificate | certificate not yet issued or wrong secret | `kubectl get certificate -n skyrict-staging`; check `skyrict-staging-wildcard-tls` secret |

## References

- ADR-003 (`docs/architecture/adr/003-staging-wildcard-dns-tls.md`)
- `infra/terraform/` - DNS modules + staging environment
- `infra/k8s/overlays/staging/` - namespace, deployment, ingresses, cert-manager
- `.github/workflows/cd-staging.yml` - the pipeline
