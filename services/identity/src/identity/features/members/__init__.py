"""Member management feature - list, re-role, and remove workspace members.

Sits above the users, memberships, roles, and sessions features: it composes
their repositories/services to expose the member-management surface used by
the workspace Members page. Removal is a soft deactivate (``users.is_active``
= False) plus session revocation and membership suspension so history and RLS
stay intact.
"""

from __future__ import annotations
