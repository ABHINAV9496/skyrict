"""Feature modules — each package owns one business domain end-to-end.

A feature owns its router, schemas, service, and repository. Features may
depend on ``core``, ``db``, ``models``, ``domain``, and ``events`` — never on
the ``api`` layer, and never on each other at runtime (enforced by
import-linter). Cross-feature wiring happens only in ``dependencies.py``.
"""
