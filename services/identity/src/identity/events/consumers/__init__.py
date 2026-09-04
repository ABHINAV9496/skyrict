"""Kafka event consumers - subscribe to domain events.

The identity service has no consumers yet. When wired, consumers will subclass
``skyrict_events.BaseConsumer`` and implement ``handle()`` for each topic the
identity domain reacts to (e.g. ``tenant.created``, ``user.deleted``). Until
then this package is intentionally empty.
"""
