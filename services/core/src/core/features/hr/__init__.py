"""HR feature package — departments, employees, leave requests, leave ledger.

Feature-based layout: every ERP module owns its ``models/``, ``ports.py`` and
``repository.py`` inside its own package under ``core.features``. The HR
repository (deferred to the integration phase) also implements the payroll
``LeaveLedgerPort`` for approved unpaid-leave reads.
"""

__all__: list[str] = []
