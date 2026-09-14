"""Markdown renderers for RAG indexing of finance AI documents (FIN-AI-004).

Mirrors the data surface of :mod:`core.features.ai_docs.pdf_renderer` so the
searchable text of a generated pack/tax summary says exactly what the branded
PDF says - the tenant's own figures, useful for citation evidence in A12.
"""

from __future__ import annotations

from typing import Any


def _fmt(value: Any) -> str:
    return f"{float(value or 0):,.2f}"


def _section_lines(header: str, rows: list[dict[str, Any]], amount_key: str) -> list[str]:
    lines = [f"## {header}", ""]
    for row in rows:
        code = row.get("code")
        name = row.get("name")
        label = f"{code} - {name}" if code else str(name or "")
        lines.append(f"- {label}: {_fmt(row.get(amount_key))}")
    lines.append("")
    return lines


def render_report_markdown(
    *, doc_type: str, snapshot_data: dict[str, Any], revision: str = ""
) -> str:
    """Render one ``pnl`` / ``balance_sheet`` pack as markdown text."""
    title = "Profit & Loss" if doc_type == "pnl" else "Balance Sheet"
    period = snapshot_data.get("period") or snapshot_data.get("as_of") or ""
    lines = [f"# {title}", ""]
    if period:
        lines.append(f"Period: {period}")
    if revision:
        lines.append(f"Revision: {revision}")
    lines.append("")

    if doc_type == "pnl":
        lines += _section_lines("Revenue", snapshot_data.get("revenue", []), "amount")
        lines.append(f"**Total Revenue**: {_fmt(snapshot_data.get('total_revenue'))}")
        lines.append("")
        lines += _section_lines("Expenses", snapshot_data.get("expenses", []), "amount")
        lines.append(f"**Total Expenses**: {_fmt(snapshot_data.get('total_expenses'))}")
        lines.append("")
        lines.append(f"**Net Income**: {_fmt(snapshot_data.get('net_income'))}")
    else:
        lines += _section_lines("Assets", snapshot_data.get("assets", []), "balance")
        lines.append(f"**Total Assets**: {_fmt(snapshot_data.get('total_assets'))}")
        lines.append("")
        lines += _section_lines("Liabilities", snapshot_data.get("liabilities", []), "balance")
        lines.append(f"**Total Liabilities**: {_fmt(snapshot_data.get('total_liabilities'))}")
        lines.append("")
        lines += _section_lines("Equity", snapshot_data.get("equity", []), "balance")
        lines.append(f"**Total Equity**: {_fmt(snapshot_data.get('total_equity'))}")
    return "\n".join(lines)


def render_tax_summary_markdown(
    *,
    period_name: str,
    start_date: Any,
    end_date: Any,
    categories: list[dict[str, Any]],
    total_input: Any,
    total_output: Any,
) -> str:
    """Render a generated tax summary as markdown text."""
    lines = [
        "# Tax Summary",
        "",
        f"Period: {period_name} ({start_date} to {end_date})",
        "",
        "## Tax categories",
        "",
    ]
    for cat in categories:
        name = str(cat.get("category") or "")
        detail = str(cat.get("detail") or "").strip()
        lines.append(
            f"- **{name}**: input {_fmt(cat.get('input_tax'))}, "
            f"output {_fmt(cat.get('output_tax'))}, net {_fmt(cat.get('net'))}"
        )
        if detail:
            lines.append(f"  - {detail}")
    lines.extend(
        [
            "",
            f"**Total input tax**: {_fmt(total_input)}",
            f"**Total output tax**: {_fmt(total_output)}",
        ]
    )
    return "\n".join(lines)
