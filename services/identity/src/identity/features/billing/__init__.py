"""Server-side billing plan catalog and tier mapping.

The catalog is the single source of truth for plan pricing, feature limits,
and the ``plan_tier`` ↔ frontend ``planId`` mapping.  The backend never reads
``apps/web`` config for authoritative plan data (see ADR-009).
"""

from __future__ import annotations
