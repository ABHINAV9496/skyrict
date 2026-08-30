"""Module-level convenience wrapper for the redaction gate.

Re-exports :class:`Redactor`, :class:`RedactionResult` and the pure
:func:`redact_text` helper so callers can import everything from the package
surface. ``RedactionResult`` is defined in ``redactor`` to avoid a circular
import (``redactor`` is the leaf that produces the result).
"""

from __future__ import annotations

from ai_agent.redaction.redactor import RedactionResult, Redactor, redact_text

__all__ = ["RedactionResult", "Redactor", "redact_text"]
