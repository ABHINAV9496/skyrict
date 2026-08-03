"""Domain event handlers — one handler per event type.

Handlers are the application-side reaction to events (for example,
invalidating sessions when a user is deleted). Consumers invoke them; keeping
them here makes the wiring explicit rather than scattered across features.
No handlers are registered yet.
"""
