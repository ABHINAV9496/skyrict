"""Payroll feature package — salary history, runs, per-run entries, settings.

Layout follows the ERP feature convention (spec §2.1/§3.2): one model file per
table under ``models/``. Shared ``Base``/mixins live in ``core.models.base``
(identity convention — no ``db/base.py``). The one cross-module reference is
``PayrollEntryModel.employee_id`` → ``features.hr.models.EmployeeModel``
(one-way, for the composite FK ``erp_payroll_entries → erp_employees``).
"""
