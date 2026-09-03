"""Payslip PDF renderer — on-demand, from frozen entry only (HR-AUT-001, Commit 3).

Regenerated every time: no BLOB storage. Uses ReportLab's ``SimpleDocTemplate``
to produce a single-page A4 payslip suitable for download or email attachment.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.domain.value_objects import Money

_WIDTH, _HEIGHT = A4

_HEADER_STYLE = ParagraphStyle(
    "payslip-header",
    parent=getSampleStyleSheet()["Heading1"],
    alignment=TA_CENTER,
    fontSize=18,
    leading=22,
    spaceAfter=4 * mm,
)

_SUBHEADER_STYLE = ParagraphStyle(
    "payslip-subheader",
    parent=getSampleStyleSheet()["Normal"],
    alignment=TA_CENTER,
    fontSize=11,
    textColor=colors.HexColor("#555555"),
    spaceAfter=6 * mm,
)

_LABEL_STYLE = ParagraphStyle(
    "payslip-label",
    parent=getSampleStyleSheet()["Normal"],
    fontSize=10,
    textColor=colors.HexColor("#666666"),
)

_VALUE_STYLE = ParagraphStyle(
    "payslip-value",
    parent=getSampleStyleSheet()["Normal"],
    fontSize=10,
    alignment=TA_RIGHT,
)

_FOOTER_STYLE = ParagraphStyle(
    "payslip-footer",
    parent=getSampleStyleSheet()["Normal"],
    alignment=TA_CENTER,
    fontSize=8,
    textColor=colors.HexColor("#999999"),
    spaceBefore=6 * mm,
)


def _fmt_money(amount: Decimal, currency: str) -> str:
    """Format a Money value as ``1,234.56 USD``."""
    return f"{amount:,.2f} {currency}"


def render_payslip_pdf(
    *,
    run_code: str,
    period_start: date,
    period_end: date,
    employee_number: str,
    employee_name: str,
    base_salary: Money,
    pay_days: int,
    gross: Money,
    deductions: Money,
    net: Money,
) -> bytes:
    """Render a single-page payslip PDF and return the raw bytes.

    The PDF is regenerated from the frozen entry each time; no caching or
    BLOB storage is involved.
    """
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

    story.append(Paragraph("Payslip", _HEADER_STYLE))
    story.append(
        Paragraph(
            f"{run_code} &mdash; {period_start.strftime('%d %b %Y')} to "
            f"{period_end.strftime('%d %b %Y')}",
            _SUBHEADER_STYLE,
        )
    )

    info_data = [
        [
            Paragraph("Employee No.", _LABEL_STYLE),
            Paragraph(employee_number, _VALUE_STYLE),
        ],
        [
            Paragraph("Employee Name", _LABEL_STYLE),
            Paragraph(employee_name, _VALUE_STYLE),
        ],
    ]
    info_table = Table(info_data, colWidths=[doc.width * 0.5] * 2)
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    story.append(info_table)
    story.append(Spacer(1, 4 * mm))

    currency = gross.currency
    rows = [
        [
            Paragraph("Description", _LABEL_STYLE),
            Paragraph("Amount", _LABEL_STYLE),
        ],
        [
            Paragraph(f"Base Salary ({pay_days} working days)", _LABEL_STYLE),
            Paragraph(_fmt_money(base_salary.amount, currency), _VALUE_STYLE),
        ],
        [
            Paragraph("Gross Pay", _LABEL_STYLE),
            Paragraph(_fmt_money(gross.amount, currency), _VALUE_STYLE),
        ],
        [
            Paragraph("Deductions", _LABEL_STYLE),
            Paragraph(_fmt_money(deductions.amount, currency), _VALUE_STYLE),
        ],
        [
            Paragraph("Net Pay", ParagraphStyle("net-bold", parent=_LABEL_STYLE, fontSize=11)),
            Paragraph(
                _fmt_money(net.amount, currency),
                ParagraphStyle("net-bold-val", parent=_VALUE_STYLE, fontSize=11),
            ),
        ],
    ]
    col_widths = [doc.width * 0.6, doc.width * 0.4]
    pay_table = Table(rows, colWidths=col_widths)
    pay_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#cccccc")),
                ("LINEBELOW", (0, 2), (-1, 2), 0.5, colors.HexColor("#e0e0e0")),
                ("LINEABOVE", (0, 4), (-1, 4), 1, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    story.append(pay_table)
    story.append(
        Paragraph(
            "This payslip is generated on demand from the approved payroll entry.",
            _FOOTER_STYLE,
        )
    )

    doc.build(story)
    return buf.getvalue()
