"""ORM models for the notification center (SKY-93).

Registers every model so ``core.features.notifications.models`` is the one
import the Alembic env registers.
"""

from __future__ import annotations

from core.features.notifications.models.event import (
    ErpNotificationEventModel,
)
from core.features.notifications.models.notification import (
    ErpNotificationModel,
)
from core.features.notifications.models.preference import (
    ErpNotificationPrefModel,
)

__all__ = [
    "ErpNotificationEventModel",
    "ErpNotificationModel",
    "ErpNotificationPrefModel",
]
