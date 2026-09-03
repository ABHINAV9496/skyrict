"""Premium "New Login Detected" security-alert email templates.

Pure presentation: takes a fully-resolved :class:`SecurityAlert` and renders
table-based, inline-styled, responsive HTML (GitHub/Stripe/Google style) plus a
plaintext fallback. No I/O, no imports from features - safe to render anywhere.

Brand: Skyrict - dark teal ``#0a2f3e`` text, sky gradient ``#aedef1 -> #4cb6e1``
accents. All dynamic values are HTML-escaped before substitution.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from string import Template

APP_NAME = "Skyrict"


@dataclass(frozen=True)
class SecurityAlert:
    """Fully-resolved payload for a new-login security alert email."""

    to: str
    full_name: str
    event_type: str
    ip_address: str
    location: str
    browser: str
    os: str
    device: str
    auth_method: str
    session_id_masked: str
    date_time: str
    review_url: str | None = None
    secure_url: str | None = None
    support_email: str = "security@skyrict.dev"
    app_name: str = APP_NAME


# --------------------------------------------------------------------------- #
# Inline SVG icons (18px, stroke-based). Role=presentation keeps screen
# readers on the text labels; Outlook desktop renders the empty alt cell.
# --------------------------------------------------------------------------- #
_ICONS = {
    "clock": '<path d="M9 5.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"/><path d="M9 7v1.8l1.3 1"/>',
    "pin": '<path d="M9 15s6-3.9 6-8.2A6 6 0 1 0 3 6.8C3 11.1 9 15 9 15Z"/><circle cx="9" cy="6.8" r="2.1"/>',
    "globe": '<circle cx="9" cy="9" r="6.2"/><path d="M2.8 9h12.4M9 2.8c1.6 1.6 2.4 3.6 2.4 6.2S10.6 14.6 9 16.2M9 2.8C7.4 4.4 6.6 6.4 6.6 9s.8 5.6 2.4 7.2"/>',
    "browser": '<rect x="2.6" y="4" width="12.8" height="9.4" rx="1.6"/><path d="M2.6 7h12.8M5.4 5.5h.01M7 5.5h.01"/>',
    "chip": '<rect x="4.4" y="4.4" width="9.2" height="9.2" rx="1.6"/><path d="M7 2.8v3M11 2.8v3M7 12.2v3M11 12.2v3M2.8 7h3M2.8 11h3M12.2 7h3M12.2 11h3"/>',
    "device": '<rect x="6" y="2.8" width="6" height="12.4" rx="1.6"/><path d="M8 13.4h2M9 2.8h.01"/>',
    "shield": '<path d="M9 2.6l5.5 2v4.1c0 3.6-2.3 6.4-5.5 7.7-3.2-1.3-5.5-4.1-5.5-7.7V4.6l5.5-2Z"/><path d="M6.4 9.2l1.8 1.8 3.4-3.5"/>',
    "id_card": '<rect x="2.6" y="4.2" width="12.8" height="9.6" rx="1.6"/><circle cx="6.4" cy="8.2" r="1.3"/><path d="M4.6 12.2c.4-1.3 1.5-1.8 3.6-1.8 1.3 0 2 .3 2.5.9M10.4 8.6h3.4M10.4 10.6h2.4"/>',
}

_ICON_TEMPLATE = (
    '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" role="presentation" '
    'aria-hidden="true" style="display:block">'
    '<g stroke="{color}" stroke-width="1.35" stroke-linecap="round" '
    'stroke-linejoin="round">{path}</g></svg>'
)


def _icon(name: str, *, color: str = "#4cb6e1") -> str:
    return _ICON_TEMPLATE.format(color=color, path=_ICONS[name])


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _detail_row(icon: str, label: str, value: str) -> str:
    """One labelled row in the login-details card."""
    return (
        f'<tr><td width="34" valign="top" style="padding:10px 0;border-bottom:1px solid #eef3f6">'
        f"{_icon(icon, color='#9fb6c6')}</td>"
        f'<td width="132" valign="top" style="padding:10px 12px 10px 4px;border-bottom:1px solid #eef3f6;'
        f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;"
        f'line-height:20px;color:#8798a5">{label}</td>'
        f'<td valign="top" style="padding:10px 0;border-bottom:1px solid #eef3f6;'
        f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;"
        f'line-height:20px;color:#0a2f3e;font-weight:600">{_esc(value)}</td></tr>'
    )


def _advice_step(number: int, title: str, body: str) -> str:
    return (
        "<tr>"
        f'<td width="30" valign="top" style="padding:8px 0">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td width="26" height="26" align="center" valign="middle" '
        f'style="width:26px;height:26px;border-radius:50%;background:#eaf6fc;'
        f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        f'font-size:12px;font-weight:700;color:#14708f">{number}</td></tr></table></td>'
        f'<td valign="top" style="padding:8px 0 8px 8px">'
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        f'font-size:13px;line-height:18px;color:#0a2f3e;font-weight:600">{_esc(title)}</div>'
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        f'font-size:12px;line-height:18px;color:#5b6b77;margin-top:2px">{_esc(body)}</div>'
        f"</td></tr>"
    )


def _button(href: str, label: str, *, primary: bool) -> str:
    if primary:
        bg, fg, border = "#0a2f3e", "#ffffff", "#0a2f3e"
    else:
        bg, fg, border = "#ffffff", "#0a2f3e", "#cbd8e0"
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 auto"><tr><td align="center" style="border-radius:8px;'
        f'background:{bg};border:1px solid {border}">'
        f'<a href="{_esc(href)}" target="_blank" '
        f'style="display:inline-block;padding:12px 26px;border-radius:8px;'
        f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        f"font-size:14px;font-weight:600;line-height:20px;text-decoration:none;"
        f'color:{fg}">{_esc(label)}</a></td></tr></table>'
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
<title>New login detected on your ${app_name} account</title>
<style>
  body,table,td,a,p { -webkit-text-size-adjust:100%; }
  body { margin:0; padding:0; background:#f4f7f9; }
  @media only screen and (max-width:620px) {
    .container { width:100% !important; }
    .row-stack { display:block !important; width:100% !important; }
    .row-stack > td { display:block !important; width:100% !important; }
    .btn-wrap { padding:6px 0 !important; }
  }
</style>
</head>
<body style="margin:0;padding:0;background:#f4f7f9;">
  <center role="article" aria-roledescription="email" aria-label="New login alert" style="width:100%;table-layout:fixed;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;background:#f4f7f9;">
    <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:600px;max-width:600px;margin:0 auto;">
      <tr><td style="padding:36px 24px 8px;">${header_logo}</td></tr>

      <!-- Card -->
      <tr>
        <td style="padding:12px 24px 8px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="background:#ffffff;border:1px solid #e6edf2;border-radius:16px;box-shadow:0 6px 24px rgba(15,47,63,0.06);">
            <!-- Alert badge -->
            <tr>
              <td style="padding:28px 32px 0;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="padding:4px 12px;border-radius:999px;background:#eaf6fc;border:1px solid #cfeafa;">
                      <span style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.9px;text-transform:uppercase;color:#14708f;">Security alert</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Title -->
            <tr>
              <td style="padding:16px 32px 0;">
                <h1 style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:24px;line-height:30px;font-weight:700;color:#0a2f3e;letter-spacing:-0.2px;">New login detected</h1>
              </td>
            </tr>

            <!-- Description -->
            <tr>
              <td style="padding:12px 32px 0;">
                <p style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:22px;color:#5b6b77;">A new device signed in to <strong style="color:#0a2f3e;">your ${app_name} account</strong>. If this was you, no action is needed. If you don't recognize this activity, secure your account right away.</p>
              </td>
            </tr>

            <!-- Login details card -->
            <tr>
              <td style="padding:20px 32px 0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background:#fbfdfe;border:1px solid #eef3f6;border-radius:12px;">
                  ${detail_rows}
                </table>
              </td>
            </tr>

            <!-- Actions -->
            <tr>
              <td style="padding:24px 32px 0;">
                <table role="presentation" class="row-stack" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    ${primary_button}
                    ${secondary_button}
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Security advice -->
            <tr>
              <td style="padding:24px 32px 8px;">
                <div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.9px;text-transform:uppercase;color:#14708f;">If this wasn't you</div>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:4px;">
                  ${advice_steps}
                </table>
              </td>
            </tr>

            <!-- Footer inside card -->
            <tr>
              <td style="padding:20px 32px 24px;">
                <div style="border-top:1px solid #eef3f6;padding-top:16px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;line-height:18px;color:#8798a5;">
                  This is an automated security notification - please don't reply to this email. Questions? Contact <a href="mailto:${support_email}" style="color:#14708f;text-decoration:none;font-weight:600;">${support_email}</a>.
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
            Sent by ${app_name} &middot; automated security notification<br>
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


def _action_buttons(alert: SecurityAlert) -> tuple[str, str]:
    if alert.review_url:
        primary = (
            '<td align="center" valign="middle" style="width:50%;padding:4px;">'
            + _button(alert.review_url, "Review activity", primary=True)
            + "</td>"
        )
    else:
        primary = "<td></td>"
    if alert.secure_url:
        secondary = (
            '<td align="center" valign="middle" class="btn-wrap" style="width:50%;padding:4px;">'
            + _button(alert.secure_url, "Secure my account", primary=False)
            + "</td>"
        )
    else:
        secondary = "<td></td>"
    return primary, secondary


def render_security_alert_html(alert: SecurityAlert) -> str:
    """Render the full HTML email body for a new-login security alert."""
    rows = [
        _detail_row("clock", "Date &amp; time", alert.date_time),
        _detail_row("pin", "Location", alert.location or "Unknown"),
        _detail_row("globe", "IP address", alert.ip_address),
        _detail_row("browser", "Browser", alert.browser),
        _detail_row("chip", "Operating system", alert.os),
        _detail_row("device", "Device", alert.device),
        _detail_row("shield", "Authentication", alert.auth_method),
        _detail_row("id_card", "Session ID", alert.session_id_masked),
    ]

    primary, secondary = _action_buttons(alert)

    advice = (
        _advice_step(
            1,
            "Change your password",
            "Use a strong, unique password and update it from your account security settings.",
        )
        + _advice_step(
            2,
            "Review active sessions",
            "Sign out of any sessions you don't recognize from your security settings.",
        )
        + _advice_step(
            3,
            "Revoke trusted devices",
            "Remove devices you no longer use so they can't access your account.",
        )
        + _advice_step(
            4,
            "Enable multi-factor auth",
            "Add a second verification step to keep your account protected even if your password leaks.",
        )
    )

    mapping = {
        "app_name": _esc(alert.app_name),
        "support_email": _esc(alert.support_email),
        "year": str(datetime.now(UTC).year),
        "header_logo": _logo_block(),
        "detail_rows": "".join(rows),
        "primary_button": primary,
        "secondary_button": secondary,
        "advice_steps": advice,
    }
    return _TEMPLATE.safe_substitute(mapping)


# --------------------------------------------------------------------------- #
# OTP / Verification-code email templates
# --------------------------------------------------------------------------- #

_OTP_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Your ${app_name} verification code</title>
<style>
  body,table,td,a,p { -webkit-text-size-adjust:100%; }
  body { margin:0; padding:0; background:#f4f7f9; }
  /* Dark theme: activated by OS preference OR .dark class on <html> */
  @media only screen and (prefers-color-scheme:dark) {
    body { background:#0b1a22 !important; }
    .email-bg { background:#0b1a22 !important; }
    .card { background:#132b36 !important; border-color:#1e3d4a !important; box-shadow:0 6px 24px rgba(0,0,0,0.3) !important; }
    .heading { color:#e8f0f3 !important; }
    .body-text { color:#9fb6c6 !important; }
    .code-box { background:#0a1f28 !important; border-color:#1e3d4a !important; }
    .code-digit { background:#0f222c !important; border-color:#1e3d4a !important; color:#e8f0f3 !important; }
    .label-badge { background:#0e2a34 !important; border-color:#1a4a5c !important; }
    .label-text { color:#4cb6e1 !important; }
    .shield-icon { color:#4cb6e1 !important; }
    .expiry-text { color:#7a99aa !important; }
    .expiry-strong { color:#e8f0f3 !important; }
    .card-footer { border-color:#1e3d4a !important; }
    .card-footer-text { color:#7a99aa !important; }
    .footer-text { color:#5b7a8a !important; }
  }
  .dark body, .dark .email-bg { background:#0b1a22 !important; }
  .dark .card { background:#132b36 !important; border-color:#1e3d4a !important; box-shadow:0 6px 24px rgba(0,0,0,0.3) !important; }
  .dark .heading { color:#e8f0f3 !important; }
  .dark .body-text { color:#9fb6c6 !important; }
  .dark .code-box { background:#0a1f28 !important; border-color:#1e3d4a !important; }
  .dark .code-digit { background:#0f222c !important; border-color:#1e3d4a !important; color:#e8f0f3 !important; }
  .dark .label-badge { background:#0e2a34 !important; border-color:#1a4a5c !important; }
  .dark .label-text { color:#4cb6e1 !important; }
  .dark .shield-icon { color:#4cb6e1 !important; }
  .dark .expiry-text { color:#7a99aa !important; }
  .dark .expiry-strong { color:#e8f0f3 !important; }
  .dark .card-footer { border-color:#1e3d4a !important; }
  .dark .card-footer-text { color:#7a99aa !important; }
  .dark .footer-text { color:#5b7a8a !important; }
  @media only screen and (max-width:480px) {
    .container { width:100% !important; padding:0 !important; }
    .card { padding:20px 16px !important; }
    .mobile-pad { padding-left:20px !important; padding-right:20px !important; }
    .mobile-pad-top { padding-left:20px !important; padding-right:20px !important; }
    .heading { font-size:20px !important; line-height:26px !important; }
    .code-digit { width:38px !important; height:46px !important; font-size:19px !important; }
    .code-digit-spacer { width:6px !important; }
    .footer-text { padding:16px 20px 32px !important; }
  }
</style>
</head>
<body style="margin:0;padding:0;background:#f4f7f9;">
  <center role="article" aria-roledescription="email" aria-label="Verification code" class="email-bg" style="width:100%;table-layout:fixed;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;background:#f4f7f9;">
    <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" align="center" style="width:600px;max-width:600px;margin:0 auto;">

      <!-- Logo -->
      <tr><td style="padding:36px 24px 8px;">${header_logo}</td></tr>

      <!-- Card -->
      <tr>
        <td style="padding:12px 24px 8px;">
          <table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0"
                 style="background:#ffffff;border:1px solid #e6edf2;border-radius:16px;box-shadow:0 6px 24px rgba(15,47,63,0.06);">

            <!-- Label badge -->
            <tr>
              <td class="mobile-pad" style="padding:28px 32px 0;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td class="label-badge" style="padding:5px 14px;border-radius:999px;background:#eaf6fc;border:1px solid #cfeafa;">
                      <span class="label-text" style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.9px;text-transform:uppercase;color:#14708f;">Verification code</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Heading -->
            <tr>
              <td class="mobile-pad" style="padding:16px 32px 0;">
                <h1 class="heading" style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:24px;line-height:30px;font-weight:700;color:#0a2f3e;letter-spacing:-0.2px;">Enter this code to continue</h1>
              </td>
            </tr>

            <!-- Body text -->
            <tr>
              <td class="mobile-pad" style="padding:12px 32px 0;">
                <p class="body-text" style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:22px;color:#5b6b77;">Use the verification code below to complete your ${app_name} signup. This code is valid for 10 minutes.</p>
              </td>
            </tr>

            <!-- Code box -->
            <tr>
              <td class="mobile-pad" style="padding:24px 32px 0;">
                <table role="presentation" class="code-box" width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background:#f4f9fb;border:1px solid #dce9ef;border-radius:12px;">
                  <tr>
                    <td align="center" valign="middle" style="padding:20px 16px;">
                      ${code_digits}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Expiry -->
            <tr>
              <td class="mobile-pad" style="padding:16px 32px 0;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td class="shield-icon" style="padding-right:8px;vertical-align:middle;color:#14708f;">
                      <svg width="16" height="16" viewBox="0 0 18 18" fill="none" role="presentation" aria-hidden="true" style="display:block">
                        <g stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M9 2.6l5.5 2v4.1c0 3.6-2.3 6.4-5.5 7.7-3.2-1.3-5.5-4.1-5.5-7.7V4.6l5.5-2Z"/>
                          <path d="M6.4 9.2l1.8 1.8 3.4-3.5"/>
                        </g>
                      </svg>
                    </td>
                    <td class="expiry-text" style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:13px;line-height:18px;color:#8798a5;">This code expires in <strong class="expiry-strong" style="color:#0a2f3e;">10 minutes</strong>. If you didn't request this, you can safely ignore this email.</td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Footer inside card -->
            <tr>
              <td class="mobile-pad" style="padding:24px 32px 24px;">
                <div class="card-footer" style="border-top:1px solid #eef3f6;padding-top:16px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:12px;line-height:18px;">
                  <span class="card-footer-text" style="color:#8798a5;">Do not share this code with anyone. ${app_name} will never ask for it via phone or email.</span>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Outer footer -->
      <tr>
        <td style="padding:20px 24px 40px;">
          <div class="footer-text" style="text-align:center;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:11px;line-height:17px;color:#9aacb8;">
            Sent by ${app_name}<br>
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


def _otp_code_digits(code: str) -> str:
    """Render the 6-digit OTP code as spaced monospace characters in a styled row."""
    digits = list(code)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto">'
        "<tr>"
        + "".join(
            f'<td class="code-digit" align="center" valign="middle" '
            f'style="width:44px;height:52px;border-radius:8px;background:#ffffff;border:1px solid #dce9ef;'
            f"font-family:'SF Mono',SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace;"
            f'font-size:22px;font-weight:700;color:#0a2f3e;letter-spacing:0;">{_esc(d)}</td>'
            + (
                '<td class="code-digit-spacer" width="10" style="width:10px;" aria-hidden="true"></td>'
                if i < len(digits) - 1
                else ""
            )
            for i, d in enumerate(digits)
        )
        + "</tr></table>"
    )


def render_otp_html(code: str, *, app_name: str = APP_NAME) -> str:
    """Render the full HTML email body for a verification-code OTP."""
    mapping = {
        "app_name": _esc(app_name),
        "year": str(datetime.now(UTC).year),
        "header_logo": _logo_block(),
        "code_digits": _otp_code_digits(code),
    }
    return _OTP_TEMPLATE.safe_substitute(mapping)


def render_otp_text(code: str, *, app_name: str = APP_NAME) -> str:
    """Render a clean plaintext fallback for a verification-code OTP."""
    spaced = " ".join(code)
    return (
        f"Your {app_name} verification code\n"
        f"\n"
        f"  {spaced}\n"
        f"\n"
        f"This code expires in 10 minutes.\n"
        f"If you didn't request this, you can safely ignore this email.\n"
        f"\n"
        f"Do not share this code with anyone. {app_name} will never ask for it via phone or email."
    )


def render_security_alert_text(alert: SecurityAlert) -> str:
    """Render a clean plaintext fallback for the same alert."""
    lines = [
        f"New login detected on your {alert.app_name} account",
        "",
        f"Hi {alert.full_name},",
        "",
        "A new device signed in to your Skyrict account. If this was you, "
        "no action is needed. If you don't recognize this activity, secure "
        "your account right away.",
        "",
        "Login details",
        f"  Date & time:      {alert.date_time}",
        f"  Location:         {alert.location or 'Unknown'}",
        f"  IP address:       {alert.ip_address}",
        f"  Browser:          {alert.browser}",
        f"  Operating system: {alert.os}",
        f"  Device:           {alert.device}",
        f"  Authentication:   {alert.auth_method}",
        f"  Session ID:       {alert.session_id_masked}",
    ]
    if alert.review_url:
        lines += ["", f"Review activity: {alert.review_url}"]
    if alert.secure_url:
        lines += [f"Secure my account: {alert.secure_url}"]
    lines += [
        "",
        "If this wasn't you, act immediately: change your password, review "
        "active sessions, revoke trusted devices, and enable multi-factor "
        "authentication.",
        "",
        f"This is an automated security notification. For help, contact {alert.support_email}.",
    ]
    return "\n".join(lines)
