"""Structured logging — thin wrapper over skyrict_common (no skyrict-logging lib).

Every log entry automatically includes request_id and tenant_id when the
structlog contextvars are bound by the middleware.
"""

from __future__ import annotations

from skyrict_common.logging import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
