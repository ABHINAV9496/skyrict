"""Domain event publishing/consuming (Kafka via skyrict-events).

Populated when the ai agent starts emitting domain events; audit-trail writes
are synchronous DB rows (core/audit_events.py), not Kafka messages.
"""
