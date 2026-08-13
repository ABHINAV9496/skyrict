"""HR feature package — employee records, leave ledger & balances.

Layout follows the ERP feature convention (spec §2.1/§3.2): one model file per
table under ``models/``. Shared ``Base``/mixins live in ``core.models.base``
(identity convention — no ``db/base.py``).
"""
