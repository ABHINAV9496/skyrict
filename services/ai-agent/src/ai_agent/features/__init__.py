"""Vertical feature slices (core convention: one package per capability).

Each slice owns its router, schemas, service, ports and repository. Populated
by the SKY-57 engine/route commits:

- ``nl_query``     natural-language inventory queries (nl_engine)
- ``restock``      restock suggestions + approval workflow
- ``anomalies``    stock anomaly detection + review workflow

Routers mount through ``api/v1/router.py``; all authorization happens at the
core monolith proxy edge before a request ever reaches these slices.
"""
