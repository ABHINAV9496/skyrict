"""Scheduled (background) work that needs the feature layer.

Lives under the API layer, not ``core/jobs``: import-linter forbids
foundations from depending on features, and these tasks orchestrate feature
services (anomaly detection) with repositories and the gateway. Requests-free
work that only touches repositories stays in ``core/jobs``.
"""
