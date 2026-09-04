# =============================================================================
# DNS module - provider contract (implementation: AWS Route 53)
#
# Every DNS provider implementation under infra/terraform/modules/dns/ MUST
# expose the same variables and outputs so an environment can switch provider
# by changing one module source + the provider block (see
# infra/terraform/README.md for the contract and how to add a provider).
# =============================================================================

variable "zone_name" {
  description = "DNS zone to manage, e.g. staging.skyrict.com (apex of the delegated zone)."
  type        = string
}

variable "create_zone" {
  description = "Create the hosted zone (true) or look up an existing one by name (false)."
  type        = bool
  default     = false
}

variable "zone_tags" {
  description = "Tags applied to the hosted zone when create_zone is true."
  type        = map(string)
  default     = {}
}

variable "records" {
  description = <<-EOT
    DNS records to create in the zone. name is relative to the zone apex
    (use "*" for a wildcard). A single record set with multiple values is
    supported via the records list.
  EOT
  type = list(object({
    name    = string
    type    = string
    ttl     = optional(number, 300)
    records = list(string)
  }))
  default = []
}
