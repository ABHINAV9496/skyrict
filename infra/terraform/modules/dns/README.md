# Terraform DNS modules - provider contract

All DNS implementations under `modules/dns/` implement **the same interface** so
an environment can switch cloud provider with a one-line change. Today only the
AWS Route 53 implementation (`route53/`) exists; Cloudflare, Google Cloud DNS,
or Azure DNS implementations can be added later as sibling modules with
identical variables and outputs.

## Module contract

| Element | Definition |
|---------|------------|
| `zone_name` | zone apex, e.g. `staging.skyrict.com` |
| `create_zone` | `true` = create + own the zone (first bootstrap); `false` = look up an existing zone by name |
| `zone_tags` | tags applied when the zone is created |
| `records` | `list(object({ name, type, ttl, records }))` - names are relative to the zone apex (`"*"` is a wildcard) |
| `zone_id` (output) | provider-specific zone identifier |
| `nameservers` (output) | authoritative NS records, for parent-zone delegation |

Example record set (what the staging environment passes in):

```hcl
records = [
  {
    name    = "*"
    type    = "CNAME"       # or "A" when the target is an IPv4 address
    ttl     = 300
    records = ["lb-1234.us-east-1.elb.amazonaws.com"]
  },
]
```

## Adding another provider

1. Create `modules/dns/<provider>/` (`main.tf`, `variables.tf`, `outputs.tf`,
   `versions.tf`) implementing the contract above.
2. In `environments/<env>/main.tf`, change the module `source` to
   `"../../modules/dns/<provider>"` and add the provider's `required_providers`
   + provider config in `provider.tf`.
3. Update `terraform.tfvars` only if the new provider needs a different zone
   model (e.g. Cloudflare zones are looked up by name, so `create_zone=false`
   stays correct).

No other changes are needed - the environment glue (record construction,
wildcard target handling, outputs) is provider-agnostic by design.
