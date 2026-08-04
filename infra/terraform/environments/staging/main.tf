# =============================================================================
# Staging environment — wildcard DNS for *.staging.skyrict.com
#
# Responsibilities:
#   1. Hosted zone staging.skyrict.com (created once, then looked up).
#   2. Wildcard record *.staging.skyrict.com -> identity ingress load balancer.
#
# TLS is deliberately NOT provisioned here: the wildcard certificate is issued
# and auto-renewed in the cluster by cert-manager (Let's Encrypt DNS-01),
# which writes its own _acme-challenge TXT records into this zone. See
# infra/k8s/overlays/staging/cert-manager/.
# =============================================================================

locals {
  tags = {
    Environment = "staging"
    ManagedBy   = "terraform"
  }

  # The ingress load balancer exposes either an IPv4 address (A record) or a
  # hostname (CNAME record). The module contract takes a typed record list, so
  # compute the type here — the DNS module itself stays provider-agnostic.
  wildcard_is_ip = can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", var.wildcard_target))

  records = var.wildcard_target == "" ? [] : [
    {
      name    = "*"
      type    = local.wildcard_is_ip ? "A" : "CNAME"
      ttl     = 300
      records = [var.wildcard_target]
    },
  ]
}

module "dns" {
  source      = "../../modules/dns/route53"
  zone_name   = var.zone_name
  create_zone = var.create_zone
  zone_tags   = local.tags
  records     = local.records
}
