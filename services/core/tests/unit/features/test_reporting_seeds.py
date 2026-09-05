"""Phase-1 report seed catalog tests (RPT-DATA-001).

The catalog is the single source of truth for the report pack used by both
migration 0036 and the tenant-provisioning hook. These tests pin its shape:

  - exactly the 12 reports from erp-phase1.md §M-RPT (unique slugs)
  - modules finance / sales / inventory / hr, three reports each
  - every SQL passes the read-only validator
  - every used bind is declared, and no declared bind is unused (tight whitelist)
  - every seed references the catalogue `erp.reports.read` permission
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.core.permissions import CATALOG, ERP_REPORTS_READ
from core.features.reporting.seeds import PHASE_1_REPORT_SEEDS
from core.features.reporting.validation import validate_read_only_sql

EXPECTED_SLUGS = frozenset(
    {
        "pnl_by_period",
        "ar_aging",
        "cash_received",
        "pipeline_value_by_stage",
        "orders_by_period",
        "top_customers",
        "stock_on_hand_vs_reorder",
        "movement_by_type",
        "slow_movers",
        "headcount_by_department",
        "leave_usage",
        "payroll_cost_by_period",
    }
)


class TestCatalogShape:
    def test_phase_one_has_twelve_reports(self) -> None:
        assert len(PHASE_1_REPORT_SEEDS) == 12

    def test_slugs_match_mrpt_spec(self) -> None:
        assert {s.slug for s in PHASE_1_REPORT_SEEDS} == EXPECTED_SLUGS

    def test_slugs_are_unique(self) -> None:
        slugs = [s.slug for s in PHASE_1_REPORT_SEEDS]
        assert len(slugs) == len(set(slugs))

    def test_modules_are_balanced(self) -> None:
        counts = Counter(s.module for s in PHASE_1_REPORT_SEEDS)
        assert counts == {"finance": 3, "sales": 3, "inventory": 3, "hr": 3}

    def test_every_seed_has_description_and_params(self) -> None:
        for seed in PHASE_1_REPORT_SEEDS:
            assert seed.title
            assert seed.description
            assert seed.params


class TestPageOneValidity:
    @pytest.mark.parametrize("seed", PHASE_1_REPORT_SEEDS)
    def test_sql_is_read_only(self, seed) -> None:
        validate_read_only_sql(seed.sql, seed.params)

    @pytest.mark.parametrize("seed", PHASE_1_REPORT_SEEDS)
    def test_used_binds_match_declared_whitelist(self, seed) -> None:
        used = validate_read_only_sql(seed.sql, seed.params)
        # No unused declarations and no undeclared uses: the whitelist is the
        # query's parameter contract.
        assert used == set(seed.params)
        assert "tenant_id" in used

    @pytest.mark.parametrize("seed", PHASE_1_REPORT_SEEDS)
    def test_permission_key_references_catalog(self, seed) -> None:
        assert seed.permission_key == ERP_REPORTS_READ
        assert seed.permission_key in CATALOG
