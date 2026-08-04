variable "aws_region" {
  description = "AWS region for Route 53 management (Route 53 is global; the region only scopes provider auth/state)."
  type        = string
  default     = "us-east-1"
}

variable "zone_name" {
  description = "Delegated staging DNS zone, e.g. staging.skyrict.com."
  type        = string
  default     = "staging.skyrict.com"
}

variable "create_zone" {
  description = "true on the very first bootstrap to create + delegate the zone; false afterwards (look up by name)."
  type        = bool
  default     = false
}

variable "wildcard_target" {
  description = "Ingress load balancer address for *.staging.skyrict.com — an IPv4 address (A record) or hostname (CNAME record). Resolved from the cluster by the CD pipeline; empty means no wildcard record is managed yet."
  type        = string
  default     = ""
}
