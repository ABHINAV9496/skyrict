"""Event schemas — add Pydantic event models here.

Each event model should:
1. Inherit from `skyrict_events.base.BaseEvent`
2. Set `event_type` as a class-level constant
3. Add domain-specific fields

Naming convention: {Entity}{Action} (PascalCase)
Topic convention: {domain}.{entity}.{action} (snake_case)

Example:

    from skyrict_events.base import BaseEvent

    class UserCreated(BaseEvent):
        event_type: str = "identity.user.created"
        user_id: str
        email: str
        tenant_id: str

    class AuthLoginSuccess(BaseEvent):
        event_type: str = "identity.auth.login_success"
        user_id: str
        ip_address: str | None = None

See services/identity/src/identity/events/producers.py for usage.
"""
