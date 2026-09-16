# Runbook: Log shipping — service stdout to aggregation

Operational guide for how Skyrict service logs are produced, collected, and
shipped to an aggregator, plus the gaps between the current deployment and the
target state. Follow the checklist in §5 before treating log aggregation as
"done" for any environment.

## 1. Log production (application layer)

Every Python service (`services/identity`, `services/core`,
`services/ai-agent`) logs through `structlog` configured in
`skyrict_common.logging`. Behavior is controlled by env vars on the service:

| Env var      | Values            | Default | Effect                                        |
| ------------ | ----------------- | ------- | --------------------------------------------- |
| `LOG_LEVEL`  | `DEBUG`..`CRITICAL` | `INFO`  | Minimum level rendered to stdout              |
| `LOG_JSON`   | `true` / `false`  | `false` | JSON lines vs. pretty console output          |

Production posture:

- `LOG_JSON=true` in all environments (see the k8s overlays).
- **Do not log secrets, credentials, or PII.** The logging module redacts
  nothing itself — callers must not include tokens/passwords/emails in log
  events (domain convention; `request_id`/`tenant_id` are the join keys).
- Expected fallbacks log at WARNING with `exc_info=True` (full traceback in
  the JSON renderer), not bare `except: pass` — audit item B1 enforces this.

## 2. Collection (runtime layer)

Services run as Kubernetes Deployments. A container writing to stdout/stderr
is captured by the container runtime (containerd) into per-pod log files under
`/var/log/pods/` on the node, rotated by the kubelet
(`--container-log-max-size`, `--container-log-max-files`; defaults 10 MiB / 5
files unless the cluster operator overrides them).

There is **no sidecar** — pods write plain stdout and rely on the node-level
shipper described in §3. Do not add a fluent-bit/vector sidecar per pod; that
would double aggregate on multi-replica services (identity runs 3 replicas).

## 3. Shipment (aggregation layer)

Target flow:

```
service stdout ──► container runtime log file ──► node log forwarder
     ──► OpenTelemetry Collector (Loki exporter) ──► Loki ──► Grafana
```

- **Node log forwarder**: fluent-bit (DaemonSet) tailing `/var/log/pods/*/*/*.log`,
  or Azure Container Insights' agent if the cluster is an AKS cluster (see §4).
- **OpenTelemetry Collector**: optional hop that parses the `structlog` JSON
  lines into structured labels (`service`, `tenant_id`, `request_id`,
  `level`) before the Loki exporter. The Collector config lives at
  `infra/observability/otel-collector-config.yaml`.
- **Loki**: log store. Query surfaces: Grafana Explore, or the Loki HTTP API
  for ad-hoc programmatic queries.

> **Known gap (follow-up)**: `infra/observability/README.md` references
> `otel-collector-config.yaml` and `prometheus.yml`, but those files do **not
> exist in the tree yet**. Shipping a collector + Loki into a cluster is
> pending a follow-up PR that adds the manifests (Helm values or base YAML)
> plus the `alerts/` rules. Until then, logs live on node storage and are
> reachable only via `kubectl logs`.

## 4. Cloud-specific caveats

### AKS (Azure Kubernetes Service) / Azure Log Analytics

- If the cluster is AKS with the **Container Insights** agent enabled, it
  mounts the node log files and ships them to the **Log Analytics workspace**
  as `ContainerLogV2` table entries. In that mode the fluent-bit DaemonSet is
  unnecessary; query `ContainerLogV2` in the workspace (KQL) instead of Loki.
- KQL example — last identity errors, tenant-scoped:

  ```kql
  ContainerLogV2
  | where PodName startswith "identity-"
  | where LogMessage has "level=error"
  | order by TimeGenerated desc
  | take 100
  ```

- Cost: Log Analytics ingestion is chargeable per GB; `LOG_LEVEL=INFO`
  (audit item B3) increases volume. Keep `LOG_JSON=true` so parsing is cheap,
  and review the workspace retention policy if volume matters.

### Self-managed / generic Kubernetes

- Container logs rotate with the kubelet defaults; tune
  `--container-log-max-size` if a busy service (ai-agent job sweeps) rotates
  logs away before the shipper reads them.
- Promtail/fluent-bit DaemonSet reads need `hostPath` access to
  `/var/log/pods` plus RBAC for the `pods/log` subresource — the daemonset
  service account must have `get`/`list` on pods.

## 5. Log-shipping checklist (per environment)

- [ ] `LOG_JSON=true` set on every service overlay.
- [ ] `LOG_LEVEL` at `INFO` in production (identity: done in audit-hardening).
- [ ] A node-level forwarder (fluent-bit DaemonSet) or AKS Container Insights agent is deployed.
- [ ] Raw logs reach an aggregator: Loki+Collector (generic) **or** Log Analytics `ContainerLogV2` (AKS).
- [ ] Alerts exist for "no logs for N minutes" on identity/core/ai-agent (aggregator-side).
- [ ] `kubectl logs -n skyrict-production deployment/identity` works for ad-hoc triage while the above is pending.

## References

- Logging module: `libs/skyrict-common/src/skyrict_common/logging.py`
- K8s manifests: `infra/k8s/overlays/*/identity/deployment.yaml` (LOG_LEVEL / LOG_JSON)
- Observability scaffolding: `infra/observability/README.md`
- Incident runbooks: `docs/runbooks/README.md`