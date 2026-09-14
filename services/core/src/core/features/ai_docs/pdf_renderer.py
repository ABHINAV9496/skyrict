"""Branded report-pack PDF renderer (FIN-AI-004 A6).

Renders P&L / balance-sheet snapshots (``snapshot_data`` passed at generation
time) to a single A4 document via ReportLab. When the artifact is a DRAFT,
a diagonal translucent "DRAFT" overlay is drawn across the page so a
watermarked PDF can never be mistaken for an approved one; approval clears
``watermarked`` and regenerates a clean copy at the next download.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _num(value: Any) -> float:
    return float(value or 0)


def _fmt(value: Any) -> str:
    return f"{_num(value):,.2f}"


def _label_style() -> ParagraphStyle:
    return ParagraphStyle(
        "pack-label",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#666666"),
    )


def _section_style() -> ParagraphStyle:
    return ParagraphStyle(
        "pack-section",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=10.5,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#111111"),
    )


def _item_style() -> ParagraphStyle:
    return ParagraphStyle(
        "pack-item",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=10,
        leftIndent=6 * mm,
    )


def _item_amount_style() -> ParagraphStyle:
    return ParagraphStyle(
        "pack-item-amount",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=10,
        alignment=TA_RIGHT,
    )


def _total_style() -> ParagraphStyle:
    return ParagraphStyle(
        "pack-total",
        parent=getSampleStyleSheet()["Normal"],
        fontSize=10.5,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )


class _WatermarkCanvas(canvas.Canvas):  # type: ignore[misc]  # reportlab canvas is untyped
    """Draws a translucent diagonal DRAFT overlay on every page."""

    def __init__(self, *args: Any, watermarked: bool, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._watermarked = watermarked

    def showPage(self) -> None:  # noqa: N802 (reportlab API name)
        if self._watermarked:
            self.saveState()
            self.translate(self._pagesize[0] / 2, self._pagesize[1] / 2)
            self.setFont("Helvetica-Bold", 64)
            self.setFillColor(colors.HexColor("#b91c1c"))
            self.setFillAlpha(0.10)
            self.rotate(45)
            self.drawCentredString(0, 0, "DRAFT")
            self.restoreState()
        super().showPage()


def _line_item(data: dict[str, Any], amount_key: str, *, side: str) -> list[Any]:
    """One account row with the amount placed on its natural side (debit/credit).

    Negative net balances are shown on the opposite side (the ledger convention
    for contra accounts)."""
    amount = _num(data.get(amount_key))
    if amount < 0:
        side = "credit" if side == "debit" else "debit"
        amount = abs(amount)
    debit = _fmt(amount) if side == "debit" else ""
    credit = _fmt(amount) if side == "credit" else ""
    return [
        Paragraph(f"{data.get('code')} - {data.get('name')}", _item_style()),
        Paragraph(debit, _item_amount_style()),
        Paragraph(credit, _item_amount_style()),
    ]


def _total_row(label: str, amount: Any, *, side: str) -> list[Any]:
    amount = _num(amount)
    if amount < 0:
        side = "credit" if side == "debit" else "debit"
        amount = abs(amount)
    debit = _fmt(amount) if side == "debit" else ""
    credit = _fmt(amount) if side == "credit" else ""
    return [
        Paragraph(label, ParagraphStyle("t", parent=_section_style(), alignment=TA_LEFT)),
        Paragraph(debit, _total_style()),
        Paragraph(credit, _total_style()),
    ]


def render_report_pdf(
    *,
    doc_type: str,
    snapshot_data: dict[str, Any],
    watermarked: bool,
    revision: str = "",
) -> bytes:
    """Render one report pack; ``doc_type`` is ``pnl`` or ``balance_sheet``."""
    title = "Profit &amp; Loss Statement" if doc_type == "pnl" else "Balance Sheet"
    header = ParagraphStyle(
        "pack-title",
        parent=getSampleStyleSheet()["Heading1"],
        alignment=TA_CENTER,
        fontSize=18,
        leading=22,
        spaceAfter=2 * mm,
    )
    sub = ParagraphStyle(
        "pack-sub",
        parent=getSampleStyleSheet()["Normal"],
        alignment=TA_CENTER,
        fontSize=10,
        textColor=colors.HexColor("#555555"),
    )
    sub_bold = ParagraphStyle(
        "pack-sub-bold",
        parent=sub,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#333333"),
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    story: list[Any] = []
    period = str(snapshot_data.get("period") or "")
    start_date = str(snapshot_data.get("from_date") or "")
    end_date = str(snapshot_data.get("to_date") or "")
    as_of = str(snapshot_data.get("as_of") or "")
    if doc_type == "pnl":
        if period and start_date and end_date:
            context = f"For the fiscal period {period} ({start_date} to {end_date})"
        elif period:
            context = f"For the fiscal period {period}"
        else:
            context = "Profit &amp; Loss Statement"
    else:
        if period and as_of:
            context = f"Balance Sheet as at {as_of} ({period})"
        elif period:
            context = f"Balance Sheet ({period})"
        elif as_of:
            context = f"Balance Sheet as at {as_of}"
        else:
            context = "Balance Sheet"
    story.append(Paragraph(title, header))
    story.append(Paragraph(context, sub_bold))
    if revision:
        story.append(Paragraph(f"Revision {revision}", sub))
    story.append(
        Paragraph(
            "&nbsp;",
            ParagraphStyle("pack-spacer", parent=sub, fontSize=2, spaceAfter=2 * mm),
        )
    )
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor("#c3cbd6"),
            spaceBefore=0,
            spaceAfter=6 * mm,
        )
    )

    n_item = ParagraphStyle("sh-col", parent=_label_style(), fontSize=10)
    d_total = ParagraphStyle("sh-total", parent=_label_style(), fontSize=10, alignment=TA_RIGHT)

    sections: list[tuple[str, list[list[Any]], dict[str, Any] | None]]
    grand: dict[str, Any]
    if doc_type == "pnl":
        sections = [
            (
                "Revenue",
                [_line_item(r, "amount", side="credit") for r in snapshot_data.get("revenue", [])],
                {
                    "label": "Total Revenue",
                    "amount": snapshot_data.get("total_revenue"),
                    "side": "credit",
                },
            ),
            (
                "Expenses",
                [_line_item(r, "amount", side="debit") for r in snapshot_data.get("expenses", [])],
                {
                    "label": "Total Expenses",
                    "amount": snapshot_data.get("total_expenses"),
                    "side": "debit",
                },
            ),
        ]
        grand = {"label": "Net Income", "amount": snapshot_data.get("net_income"), "side": "credit"}
    else:
        sections = [
            (
                "Assets",
                [_line_item(r, "balance", side="debit") for r in snapshot_data.get("assets", [])],
                {
                    "label": "Total Assets",
                    "amount": snapshot_data.get("total_assets"),
                    "side": "debit",
                },
            ),
            (
                "Liabilities",
                [
                    _line_item(r, "balance", side="credit")
                    for r in snapshot_data.get("liabilities", [])
                ],
                {
                    "label": "Total Liabilities",
                    "amount": snapshot_data.get("total_liabilities"),
                    "side": "credit",
                },
            ),
            (
                "Equity",
                [_line_item(r, "balance", side="credit") for r in snapshot_data.get("equity", [])],
                {
                    "label": "Total Equity",
                    "amount": snapshot_data.get("total_equity"),
                    "side": "credit",
                },
            ),
        ]
        grand = {
            "label": "Total Liabilities & Equity",
            "amount": _num(snapshot_data.get("total_liabilities"))
            + _num(snapshot_data.get("total_equity")),
            "side": "credit",
        }

    rows: list[list[Any]] = [
        [Paragraph("Account", n_item), Paragraph("Debit", d_total), Paragraph("Credit", d_total)]
    ]
    for section_name, section_rows, summary in sections:
        rows.append(
            [
                Paragraph(section_name, _section_style()),
                Paragraph("", _section_style()),
                Paragraph("", _section_style()),
            ]
        )
        rows += section_rows
        if summary:
            rows.append(_total_row(summary["label"], summary["amount"], side=summary["side"]))
    rows.append(_total_row(grand["label"], grand["amount"], side=grand["side"]))

    table = Table(rows, colWidths=[doc.width * 0.6, doc.width * 0.2, doc.width * 0.2], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4d9e1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#999999")),
            ]
        )
    )
    for i, row in enumerate(rows[1:], start=1):
        if isinstance(row[0], Paragraph) and row[0].style.name == "pack-section":
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eef1f5")),
                        ("LINEABOVE", (0, i), (-1, i), 0.25, colors.HexColor("#c3cbd6")),
                    ]
                )
            )
    grand_index = len(rows) - 1
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, grand_index), (-1, grand_index), 1.5, colors.HexColor("#111111")),
                ("LINEBELOW", (0, grand_index), (-1, grand_index), 0.5, colors.HexColor("#8a94a6")),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Generated by Skyrict AI Docs. Figures are from the referenced approved "
            "financial snapshot and may not include closed-period adjustments."
            if watermarked
            else "Approved financial document - Skyrict AI Docs.",
            ParagraphStyle(
                "pack-footer",
                parent=getSampleStyleSheet()["Normal"],
                alignment=TA_CENTER,
                fontSize=8,
                textColor=colors.HexColor("#999999"),
            ),
        )
    )
    doc.build(story, canvasmaker=lambda *a, **k: _WatermarkCanvas(*a, **k, watermarked=watermarked))
    return buf.getvalue()
