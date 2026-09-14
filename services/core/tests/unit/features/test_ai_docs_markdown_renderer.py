"""Unit tests for the RAG text renderers (FIN-AI-004 finance-doc indexing)."""

from __future__ import annotations

from decimal import Decimal

from core.features.ai_docs.text_renderer import (
    render_report_markdown,
    render_tax_summary_markdown,
)


class TestReportRenderer:
    def test_pnl_renders_revenue_expenses_and_net(self) -> None:
        text = render_report_markdown(
            doc_type="pnl",
            snapshot_data={
                "period": "Q3 2026",
                "revenue": [{"code": "4000", "name": "Sales", "amount": "1200.5"}],
                "total_revenue": "1200.5",
                "expenses": [{"code": "5000", "name": "Rent", "amount": "200"}],
                "total_expenses": "200",
                "net_income": "1000.5",
            },
            revision="2",
        )
        assert "# Profit & Loss" in text
        assert "Period: Q3 2026" in text
        assert "Revision: 2" in text
        assert "4000 - Sales: 1,200.50" in text
        assert "**Total Revenue**: 1,200.50" in text
        assert "**Net Income**: 1,000.50" in text

    def test_balance_sheet_renders_three_account_blocks(self) -> None:
        text = render_report_markdown(
            doc_type="balance_sheet",
            snapshot_data={
                "as_of": "2026-09-30",
                "assets": [{"code": "1000", "name": "Cash", "balance": "500"}],
                "total_assets": "500",
                "liabilities": [],
                "total_liabilities": "0",
                "equity": [{"code": "3000", "name": "Retained", "balance": "500"}],
                "total_equity": "500",
            },
        )
        assert "# Balance Sheet" in text
        assert "Period: 2026-09-30" in text
        assert "## Assets" in text
        assert "1000 - Cash: 500.00" in text
        assert "## Liabilities" in text
        assert "**Total Equity**: 500.00" in text


class TestTaxSummaryRenderer:
    def test_renders_categories_and_totals(self) -> None:
        text = render_tax_summary_markdown(
            period_name="Q3 2026",
            start_date="2026-07-01",
            end_date="2026-09-30",
            categories=[
                {
                    "category": "Sales",
                    "detail": "Output tax on sales",
                    "input_tax": "0",
                    "output_tax": "120",
                    "net": "120",
                }
            ],
            total_input=Decimal("50"),
            total_output=Decimal("120"),
        )
        assert "# Tax Summary" in text
        assert "Period: Q3 2026 (2026-07-01 to 2026-09-30)" in text
        assert "**Sales**: input 0.00, output 120.00, net 120.00" in text
        assert "  - Output tax on sales" in text
        assert "**Total input tax**: 50.00" in text
        assert "**Total output tax**: 120.00" in text
