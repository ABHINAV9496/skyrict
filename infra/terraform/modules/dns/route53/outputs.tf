output "zone_id" {
  description = "Hosted zone identifier (Route 53 zone ID)."
  value       = local.zone_id
}

output "nameservers" {
  description = "Authoritative nameservers for the zone. Null when the zone was looked up (already delegated)."
  value       = var.create_zone ? aws_route53_zone.new[0].name_servers : null
}
