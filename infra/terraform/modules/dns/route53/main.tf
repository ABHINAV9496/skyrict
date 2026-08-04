# =============================================================================
# AWS Route 53 implementation of the DNS module contract.
# =============================================================================

locals {
  zone_id = var.create_zone ? aws_route53_zone.new[0].id : data.aws_route53_zone.existing[0].zone_id
}

# Look up a pre-existing hosted zone (the common path once an environment is
# bootstrapped — the zone was created and delegated in a previous apply).
data "aws_route53_zone" "existing" {
  count        = var.create_zone ? 0 : 1
  name         = var.zone_name
  private_zone = false
}

# Create the hosted zone on first bootstrap. The caller must delegate the
# zone from the parent domain (add NS records from the `nameservers` output
# at the registrar / parent hosted zone) before DNS-01 challenges can succeed.
resource "aws_route53_zone" "new" {
  count = var.create_zone ? 1 : 0
  name  = var.zone_name
  tags  = var.zone_tags
}

resource "aws_route53_record" "records" {
  for_each = { for idx, record in var.records : "${record.type}-${record.name}-${idx}" => record }

  zone_id = local.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = each.value.ttl
  records = each.value.records
}
