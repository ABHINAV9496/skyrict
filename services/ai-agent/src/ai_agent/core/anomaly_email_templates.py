"""Critical-anomaly email templates (INV-AI-002, spec §4.3).

Pure presentation: takes a fully-resolved :class:`CriticalAnomalyAlert` and
renders a borderless, inline-styled, responsive HTML body plus a plaintext
fallback. No I/O, no imports from features — safe to render anywhere.

Security rules (spec §4.5): anomaly descriptions never include cost/price
data (guaranteed by the rule engine), and every dynamic value is HTML-escaped
on substitution. The email identifies the tenant by id slug only.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from string import Template

APP_NAME = "Skyrict"


@dataclass(frozen=True, slots=True)
class CriticalAnomalyAlert:
    """Fully-resolved payload for one critical-anomaly admin alert."""

    to: str
    tenant_id: str
    anomaly_id: str
    anomaly_type: str
    severity: str
    title: str
    description: str
    status: str
    created_at: str
    review_url: str | None = None
    app_name: str = APP_NAME


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _detail_row(label: str, value: str) -> str:
    return (
        "<tr>"
        f'<td width="150" valign="top" style="padding:9px 0;border-bottom:1px solid #eef3f6;'
        f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;"
        f'line-height:20px;color:#8798a5">{_esc(label)}</td>'
        f'<td valign="top" style="padding:9px 0;border-bottom:1px solid #eef3f6;'
        f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;"
        f'line-height:20px;color:#0a2f3e;font-weight:600">{_esc(value)}</td>'
        "</tr>"
    )


def _button(href: str, label: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 auto"><tr><td align="center" style="border-radius:8px;'
        'background:#0a2f3e;border:1px solid #0a2f3e">'
        f'<a href="{_esc(href)}" target="_blank" '
        'style="display:inline-block;padding:12px 26px;border-radius:8px;'
        "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "font-size:14px;font-weight:600;line-height:20px;text-decoration:none;"
        f'color:#ffffff">{_esc(label)}</a></td></tr></table>'
    )


def _logo_block() -> str:
    """Skyrict logo mark (inline SVG, brand gradient) + wordmark."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td valign="middle">'
        '<svg width="34" height="34" viewBox="0 0 32 32" role="img" aria-label="Skyrict" '
        'style="display:block">'
        '<defs><linearGradient id="skym" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#aedef1"/><stop offset="100%" stop-color="#4cb6e1"/>'
        "</linearGradient></defs>"
        '<rect width="32" height="32" rx="9" fill="url(#skym)"/>'
        '<g stroke="#0a2f3e" stroke-width="2.6" stroke-linecap="round">'
        '<path d="M9 22v-4"/><path d="M14 22v-8"/><path d="M19 22V11"/><path d="M24 22v-13"/>'
        '</g><circle cx="24" cy="9" r="2.1" fill="#0a2f3e" stroke="none"/></svg>'
        '</td><td style="padding-left:10px">'
        '<span style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'font-size:19px;font-weight:700;letter-spacing:-0.2px;color:#0a2f3e">Skyrict</span>'
        "</td></tr></table>"
    )


_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>Critical inventory anomaly detected</title>
<style>
  body,table,td,a,p { -webkit-text-size-adjust:100%; }
  body { margin:0; padding:0; background:#f4f7f9; }
  @media only screen and (max-width:620px) {
    .container { width:100% !important; }
    .btn-wrap { padding:6px 0 !important; }
  }
</style>
</head>
<body style="margin:0;padding:0;background:#f4f7f9;">
  <center role="article" aria-roledescription="email" aria-label="Critical anomaly alert" style="width:100%;table-layout:fixed;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;background:#f4f7f9;">
    <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:600px;max-width:600px;margin:0 auto;">
      <tr><td style="padding:36px 24px 8px;">${header_logo}</td></tr>

      <!-- Card -->
      <tr>
        <td style="padding:12px 24px 8px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="background:#ffffff;border:1px solid #e6edf2;border-radius:16px;box-shadow:0 6px 24px rgba(15,47,63,0.06);">
            <!-- Severity badge -->
            <tr>
              <td style="padding:28px 32px 0;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="padding:4px 12px;border-radius:999px;background:#fdecea;border:1px solid #f5c6c0;">
                      <span style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.9px;text-transform:uppercase;color:#b42318;">Critical anomaly</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Title -->
            <tr>
              <td style="padding:16px 32px 0;">
                <h1 style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:24px;line-height:30px;font-weight:700;color:#0a2f3e;letter-spacing:-0.2px;">${title}</h1>
              </td>
            </tr>

            <!-- Description -->
            <tr>
              <td style="padding:12px 32px 0;">
                <p style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:22px;color:#5b6b77;">${description}</p>
              </td>
            </tr>

            <!-- Details card -->
            <tr>
              <td style="padding:20px 32px 0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background:#fbfdfe;border:1px solid #eef3f6;border-radius:12px;">
                  ${detail_rows}
                </table>
              </td>
            </tr>

            <!-- Action -->
            <tr>
              <td style="padding:24px 32px 8px;">
                ${review_button}
              </td>
            </tr>

            <!-- Footer inside card -->
            <tr>
              <td style="padding:20px 32px 24px;">
                <div style="border-top:1px solid #eef3f6;padding-top:16px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;line-height:18px;color:#8798a5;">
                  This is an automated inventory alert — please don't reply to this email. Anomaly descriptions never include cost or price data.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Outer footer -->
      <tr>
        <td style="padding:20px 24px 40px;">
          <div style="text-align:center;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;line-height:17px;color:#9aacb8;">
            Sent by ${app_name} &middot; automated inventory alert<br>
            &copy; ${year} Skyrict Technologies. All rights reserved.
          </div>
        </td>
      </tr>
    </table>
  </center>
</body>
</html>
"""
)


def render_anomaly_alert_html(alert: CriticalAnomalyAlert) -> str:
    """Render the full HTML body for a critical-anomaly admin alert."""
    details = [
        _detail_row("Anomaly ID", alert.anomaly_id),
        _detail_row("Type", alert.anomaly_type),
        _detail_row("Tenant", alert.tenant_id),
        _detail_row("Status", alert.status),
        _detail_row("Detected", alert.created_at),
    ]
    button = _button(alert.review_url, "Review anomaly") if alert.review_url else "<div></div>"

    mapping = {
        "app_name": _esc(alert.app_name),
        "year": str(datetime.now(UTC).year),
        "header_logo": _logo_block(),
        "title": _esc(alert.title),
        "description": _esc(alert.description),
        "detail_rows": "".join(details),
        "review_button": button,
    }
    return _TEMPLATE.safe_substitute(mapping)


def render_anomaly_alert_text(alert: CriticalAnomalyAlert) -> str:
    """Render a clean plaintext fallback for the same alert."""
    lines = [
        f"CRITICAL inventory anomaly ({alert.severity})",
        "",
        alert.title,
        "",
        alert.description,
        "",
        "Details",
        f"  Anomaly ID: {alert.anomaly_id}",
        f"  Type:       {alert.anomaly_type}",
        f"  Tenant:     {alert.tenant_id}",
        f"  Status:     {alert.status}",
        f"  Detected:   {alert.created_at}",
    ]
    if alert.review_url:
        lines += ["", f"Review anomaly: {alert.review_url}"]
    lines += [
        "",
        "This is an automated inventory alert. Anomaly descriptions never "
        "include cost or price data.",
        "",
        f"Sent by {alert.app_name}.",
    ]
    return "\n".join(lines)
