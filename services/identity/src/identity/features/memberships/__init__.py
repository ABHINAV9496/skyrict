"""Membership feature — the canonical user<->tenant relationship.

A membership is created INVITED at invitation time (no placeholder user),
flips to ACTIVE when the invitee accepts and a user materializes, and moves
between ACTIVE and SUSPENDED by admin action. ``users.tenant_id`` stays
denormalized for RLS; membership is the source of truth for lifecycle.
"""

from __future__ import annotations
