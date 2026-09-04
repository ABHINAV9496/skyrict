output "zone_id" {
  description = "Route 53 hosted zone ID for the staging domain."
  value       = module.dns.zone_id
}

output "nameservers" {
  description = "Authoritative nameservers for staging.skyrict.com - add these as NS records in the parent skyrict.com zone once (first bootstrap only)."
  value       = module.dns.nameservers
}

output "wildcard_record_fqdn" {
  description = "Fully qualified wildcard record created by this environment."
  value       = var.wildcard_target == "" ? null : "*.${var.zone_name} -> ${var.wildcard_target}"
}
