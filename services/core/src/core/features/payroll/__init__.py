"""Payroll feature package — runs, entries, compensation, settings.

Feature-based layout: every ERP module owns its ``models/``, ``ports.py`` and
``repository.py`` inside its own package under ``core.features``. The payroll
service consumes ``LeaveLedgerPort`` (implemented by ``features.hr``) for the
unpaid-leave proration input.
"""

__all__: list[str] = []
