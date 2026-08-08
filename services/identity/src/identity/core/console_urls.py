"""Security-console URL derivation for alert emails — tenant + environment aware.

The workspace surface lives on ``{tenant_slug}.{apex}``, so action buttons in
security-alert emails must resolve to the *tenant's* console, not a shared one.
Resolution order (see ``Settings.SECURITY_CONSOLE_BASE_URL``):

1. Explicit override — a literal base, or one containing a ``{slug}``
   placeholder that is substituted with the tenant slug.
2. Staging/production: ``https://{slug}.{BASE_DOMAIN}``.
3. Dev/test: ``http://{slug}.localhost:{SECURITY_CONSOLE_DEV_PORT}``.

Returns ``None`` when no tenant slug or base can be resolved — callers then
omit the action buttons rather than emit a dead link.
"""

from __future__ import annotations

from identity.core.config import Environment, settings


def security_console_base_url(*, tenant_slug: str | None) -> str | None:
    """Absolute workspace origin (no path) for a tenant's security console."""
    if not tenant_slug:
        return None

    override = settings.SECURITY_CONSOLE_BASE_URL.strip()
    if override:
        return override.format(slug=tenant_slug) if "{slug}" in override else override

    if settings.ENVIRONMENT in (Environment.STAGING, Environment.PRODUCTION):
        apex = settings.BASE_DOMAIN.strip()
        if not apex:
            return None
        return f"https://{tenant_slug}.{apex}"

    return f"http://{tenant_slug}.localhost:{settings.SECURITY_CONSOLE_DEV_PORT}"
