"""Application configuration — pydantic-settings, env-driven, fail-fast on missing secrets.

Single source of truth for ALL configuration. Application code must never
call os.getenv() directly — everything routes through the ``settings`` object.
"""

from __future__ import annotations

import enum
import ipaddress
import sys
from pathlib import Path  # noqa: TC003  # pydantic resolves annotations at runtime

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(enum.StrEnum):
    """Deployment environments — exactly four, no ad-hoc values."""

    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """All configuration loaded from environment variables.

    Prefix: IDENTITY_ (set via .env or shell environment).
    CRITICAL vars (DATABASE_URL, JWT keys, REDIS_URL, JWKS) have NO defaults —
    the process refuses to start if they are missing.
    """

    model_config = SettingsConfigDict(
        env_prefix="IDENTITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Environment ---
    ENVIRONMENT: Environment = Field(
        default=Environment.DEV,
        description="deployment environment: dev, test, staging, production",
    )
    DEBUG: bool = Field(default=False, description="enable debug mode")

    # --- Database (CRITICAL — no default) ---
    DATABASE_URL: str = Field(..., description="async PostgreSQL connection string — REQUIRED")

    # --- Redis (CRITICAL — no default) ---
    REDIS_URL: str = Field(..., description="Redis connection — REQUIRED")

    # --- JWT RS256 (CRITICAL — all four required) ---
    JWT_PRIVATE_KEY_PATH: Path = Field(
        ..., description="path to RSA private key PEM for signing — REQUIRED"
    )
    JWT_PUBLIC_KEY_PATH: Path = Field(
        ..., description="path to RSA public key PEM for verification — REQUIRED"
    )
    JWKS_ISSUER: str = Field(
        ..., description="JWT issuer claim (iss) — REQUIRED, e.g. https://auth.skyrict.io"
    )
    JWKS_AUDIENCE: str = Field(
        ..., description="JWT audience claim (aud) — REQUIRED, e.g. api.skyrict.io"
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, description="access token TTL")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="refresh token TTL")
    MAX_CONCURRENT_SESSIONS: int = Field(
        default=5, description="max active sessions per user — oldest are evicted"
    )
    HANDOFF_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, description="TTL for single-use onboarding handoff tokens"
    )

    # --- CORS ---
    CORS_ORIGINS: list[str] = Field(
        default=[],
        description="allowed CORS origins — must be explicit, never '*' in staging/production",
    )

    # --- IP extraction (trusted proxies) ---
    TRUSTED_PROXIES: list[str] = Field(
        default=[],
        description=(
            "IP addresses or CIDR blocks of trusted reverse proxies (e.g. "
            "'10.0.0.10' or '10.0.0.0/24'). When a request arrives from a "
            "trusted peer, the real client IP is read from the rightmost "
            "X-Forwarded-For entry appended by that proxy. Empty means no "
            "proxy is trusted: forwarded headers are ignored and the direct "
            "TCP peer is recorded, so spoofed X-Forwarded-For headers are "
            "never honoured."
        ),
    )

    # --- Logging ---
    LOG_LEVEL: str = Field(default="INFO", description="log level")
    LOG_JSON: bool = Field(default=True, description="JSON log output")

    # --- Multi-tenancy ---
    DEFAULT_TENANT_ID: str = Field(
        default="00000000-0000-0000-0000-000000000001",
        description="default tenant ID for single-tenant or bootstrap",
    )
    BASE_DOMAIN: str = Field(
        default="",
        description=(
            "production tenant base domain, e.g. 'skyrict.com' — the first "
            "label of a Host like acme.skyrict.com is the tenant slug. Required "
            "in staging/production; ignored in dev/test which resolve tenants "
            "from the X-Tenant-Slug header injected by nginx."
        ),
    )

    # --- Password policy ---
    PASSWORD_MIN_LENGTH: int = Field(default=12, description="minimum password length")
    PASSWORD_REQUIRE_UPPERCASE: bool = Field(default=True)
    PASSWORD_REQUIRE_LOWERCASE: bool = Field(default=True)
    PASSWORD_REQUIRE_DIGIT: bool = Field(default=True)
    PASSWORD_REQUIRE_SPECIAL: bool = Field(default=True)

    # --- Rate limiting ---
    RATE_LIMIT_LOGIN: int = Field(default=5, description="max login attempts per window")
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=300, description="rate limit window")
    RATE_LIMIT_LOGIN_IP: int = Field(
        default=50,
        description="coarse max login attempts per source IP per window (anti-spraying)",
    )
    RATE_LIMIT_FAIL_CLOSED: bool = Field(
        default=False,
        description=(
            "When true, rate limiting FAILS CLOSED on Redis errors (rejects the "
            "request) instead of failing open. Keep false unless an outage must "
            "shut down auth rather than allow traffic."
        ),
    )
    RATE_LIMIT_REGISTER: int = Field(
        default=5, description="max self-service registrations per IP per window"
    )
    RATE_LIMIT_REGISTER_WINDOW_SECONDS: int = Field(
        default=3600, description="register rate limit window (seconds)"
    )

    # --- Email verification ---
    VERIFICATION_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60, description="email verification token TTL (minutes)"
    )
    EMAIL_VERIFICATION_BASE_URL: str = Field(
        default="",
        description="base URL for verification links, e.g. https://app.skyrict.io/verify-email",
    )

    # --- Email delivery (SMTP) ---
    EMAIL_SMTP_HOST: str = Field(
        default="",
        description=(
            "SMTP relay host for transactional email. Empty selects the "
            "log-only transport (dev/test default). Dev: 'mailhog' or "
            "'localhost' for the MailHog container."
        ),
    )
    EMAIL_SMTP_PORT: int = Field(default=1025, description="SMTP relay port")
    EMAIL_SMTP_USERNAME: str = Field(
        default="", description="SMTP auth username (optional, MailHog needs none)"
    )
    EMAIL_SMTP_PASSWORD: str = Field(
        default="", description="SMTP auth password (optional, MailHog needs none)"
    )
    EMAIL_SMTP_USE_TLS: bool = Field(
        default=False, description="enable STARTTLS when connecting to the relay"
    )
    EMAIL_FROM_ADDR: str = Field(
        default="Skyrict <no-reply@skyrict.dev>",
        description="From address for transactional email",
    )

    # --- Security alert email ---
    GEOIP_DB_PATH: str = Field(
        default="",
        description=(
            "Path to a MaxMind GeoLite2-City.mmdb database. Empty disables "
            "geolocation — new-login emails then show only the masked IP. "
            "Download with scripts/geolite2/download-geolite2.py."
        ),
    )
    SECURITY_CONSOLE_BASE_URL: str = Field(
        default="",
        description=(
            "Base origin (no trailing slash, no path) for security-action "
            "links in alert emails. May be a literal base or contain a "
            "{slug} placeholder, e.g. 'https://{slug}.skyrict.com'. Empty "
            "auto-derives per environment: https://{slug}.{BASE_DOMAIN} in "
            "staging/production, http://{slug}.localhost:3000 in dev/test. "
            "Buttons are omitted when no base can be resolved."
        ),
    )
    SECURITY_CONSOLE_DEV_PORT: int = Field(
        default=3000,
        description="port used in auto-derived alert URLs for dev/test (apex: localhost)",
    )
    SECURITY_SUPPORT_EMAIL: str = Field(
        default="security@skyrict.dev",
        description="Support contact shown in the footer of security alert emails",
    )

    # --- Onboarding wizard (SKY-30) ---
    TURNSTILE_SITE_KEY: str = Field(
        default="",
        description="Cloudflare Turnstile site key (served to the browser)",
    )
    TURNSTILE_SECRET_KEY: str = Field(
        default="",
        description=(
            "Cloudflare Turnstile secret key for server-side siteverify. Empty "
            "in dev/test allows the wizard to run without a real Cloudflare "
            "account; staging/production fail closed when it is missing."
        ),
    )
    OTP_EXPIRE_SECONDS: int = Field(default=600, description="email OTP TTL (seconds)")
    OTP_MAX_ATTEMPTS: int = Field(default=5, description="OTP verify attempts before lockout")
    OTP_RESEND_COOLDOWN_SECONDS: int = Field(default=60, description="OTP resend cooldown")
    VERIFICATION_TOKEN_TTL_SECONDS: int = Field(
        default=1800, description="wizard verificationToken TTL (seconds)"
    )
    ONBOARDING_PASSWORD_MIN_LENGTH: int = Field(
        default=12, description="minimum password length for the onboarding wizard"
    )
    SIGNUP_START_RATE_LIMIT: int = Field(
        default=5, description="max /signup/start calls per IP per window"
    )
    SIGNUP_CODE_RATE_LIMIT: int = Field(
        default=10, description="max /signup/send-code calls per email per window"
    )
    SIGNUP_VERIFY_RATE_LIMIT: int = Field(
        default=10, description="max /signup/verify-code attempts per email per window"
    )
    SIGNUP_CHECK_RATE_LIMIT: int = Field(
        default=60, description="max /signup/check-email|check-slug calls per IP per window"
    )
    CAPTCHA_TTL_SECONDS: int = Field(
        default=300, description="text CAPTCHA challenge TTL (seconds)"
    )
    CAPTCHA_MAX_ATTEMPTS: int = Field(
        default=5, description="max verify attempts before a challenge is revoked"
    )
    SIGNUP_CAPTCHA_RATE_LIMIT: int = Field(
        default=30, description="max /signup/captcha issues per IP per window"
    )
    # --- MFA (CRITICAL — no default) ---
    MFA_ENCRYPTION_KEY: str = Field(
        ...,
        description=(
            "Fernet key used to encrypt TOTP secrets at rest — REQUIRED. "
            'Generate with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ),
    )
    MFA_TOTP_ISSUER: str = Field(
        default="Skyrict", description="issuer name embedded in TOTP provisioning URIs"
    )
    MFA_CHALLENGE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL of a login mfaToken challenge before it expires (seconds)",
    )
    MFA_CHALLENGE_MAX_ATTEMPTS: int = Field(
        default=5, description="max code attempts before a login mfaToken challenge is revoked"
    )
    RATE_LIMIT_MFA_VERIFY: int = Field(
        default=20,
        description=(
            "coarse per-IP/per-token limit on MFA challenge verifies; the "
            "stricter per-challenge MFA_CHALLENGE_MAX_ATTEMPTS binds first"
        ),
    )
    MFA_ENROLL_MAX_ATTEMPTS: int = Field(
        default=5,
        description=(
            "max failed setup-confirmation verifies (POST /mfa/verify) before "
            "the user is locked out for MFA_ENROLL_LOCKOUT_SECONDS"
        ),
    )
    MFA_ENROLL_LOCKOUT_SECONDS: int = Field(
        default=300,
        description="lockout window for failed MFA enrollment verifies (seconds)",
    )
    RATE_LIMIT_MFA_ENROLL: int = Field(
        default=20,
        description="coarse per-IP/per-user limit on MFA enrollment verifies",
    )
    RATE_LIMIT_MFA_BACKUP_CODES: int = Field(
        default=3,
        description="max backup-code regenerations per user per window",
    )

    # --- Avatar uploads ---
    AVATAR_STORAGE_BACKEND: str = Field(
        default="local",
        description="avatar storage backend: 'local' (filesystem) or 's3'",
    )
    AVATAR_STORAGE_LOCAL_DIR: str = Field(
        default="./data/avatars",
        description="base directory for the local avatar storage backend",
    )
    AVATAR_S3_BUCKET: str = Field(
        default="", description="S3 bucket for avatars (required when backend='s3')"
    )
    AVATAR_S3_PREFIX: str = Field(default="avatars", description="S3 key prefix for avatar objects")
    AVATAR_S3_REGION: str = Field(default="", description="AWS region of the avatar S3 bucket")

    # --- Derived (loaded from files at validation time) ---
    jwt_private_key: str = ""
    jwt_public_key: str = ""

    @property
    def trusted_proxy_networks(self) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        """Trusted-proxy entries as network objects for cheap membership checks."""
        return tuple(ipaddress.ip_network(entry, strict=False) for entry in self.TRUSTED_PROXIES)

    # ------------------------------------------------------------------
    # Validators — run in definition order (pydantic v2)
    # ------------------------------------------------------------------

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, value: object) -> object:
        """Accept a comma-separated string or a list; reject malformed entries.

        ``IDENTITY_TRUSTED_PROXIES=10.0.0.1,10.0.0.0/24,2001:db8::/32`` is valid
        env syntax; a bare IP is expanded to a /32 (IPv4) or /128 (IPv6)
        network by ``ip_network(..., strict=False)``.
        """
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if not isinstance(value, list):
            return value
        for entry in value:
            if not isinstance(entry, str):
                raise ValueError(f"TRUSTED_PROXIES entry must be a string, got {entry!r}")
            try:
                ipaddress.ip_network(entry.strip(), strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"TRUSTED_PROXIES entry {entry!r} is not a valid IP address or CIDR block"
                ) from exc
        return [entry.strip() for entry in value]

    @model_validator(mode="after")
    def load_rsa_keys(self) -> Settings:
        """Load RSA key files and fail immediately if missing or unreadable."""
        errors: list[str] = []

        for label, path_attr, dest_attr in [
            ("JWT_PRIVATE_KEY_PATH", "JWT_PRIVATE_KEY_PATH", "jwt_private_key"),
            ("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_PATH", "jwt_public_key"),
        ]:
            path: Path = getattr(self, path_attr)
            if not path.exists():
                errors.append(f"{label}: file not found at {path}")
            elif not path.is_file():
                errors.append(f"{label}: path is not a file ({path})")
            else:
                try:
                    content = path.read_text(encoding="utf-8")
                    if "PRIVATE KEY" not in content and "PUBLIC KEY" not in content:
                        errors.append(f"{label}: file does not appear to contain a PEM key")
                    else:
                        setattr(self, dest_attr, content)
                except OSError as exc:
                    errors.append(f"{label}: cannot read {path}: {exc}")

        if errors:
            print(
                f"FATAL: {len(errors)} configuration error(s):\n"
                + "\n".join(f"  - {e}" for e in errors),
                file=sys.stderr,
            )
            sys.exit(1)

        return self

    @model_validator(mode="after")
    def validate_mfa_encryption_key(self) -> Settings:
        """Fail-fast when MFA_ENCRYPTION_KEY is missing or not a valid Fernet key."""
        from cryptography.fernet import Fernet

        try:
            Fernet(self.MFA_ENCRYPTION_KEY.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "MFA_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from exc
        return self

    @model_validator(mode="after")
    def production_safety(self) -> Settings:
        """
        Fail-fast guards that apply ONLY in staging and production.

        Runs after load_rsa_keys so all fields are populated.
        Checks:
          1. JWT key paths must not point at committed test fixtures.
          2. DEBUG must be False.
          3. CORS_ORIGINS must not contain wildcard '*'.
          4. BASE_DOMAIN must be set (tenant subdomain resolution).
        """
        if self.ENVIRONMENT not in (Environment.STAGING, Environment.PRODUCTION):
            return self

        errors: list[str] = []

        # Check 1: test fixture keys
        for label, path_attr in [
            ("JWT_PRIVATE_KEY_PATH", "JWT_PRIVATE_KEY_PATH"),
            ("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_PATH"),
        ]:
            path: Path = getattr(self, path_attr)
            if "tests/fixtures" in path.as_posix():
                errors.append(
                    f"Refusing to start: {label} points at a public test "
                    f"fixture ({path}). Production and staging must use a "
                    f"secret-manager-provisioned key, never the committed "
                    f"dev/test keypair."
                )

        # Check 2: DEBUG must be off
        if self.DEBUG:
            errors.append(
                "Refusing to start: DEBUG=true is not allowed in staging/production. "
                "Set DEBUG=false or omit it entirely."
            )

        # Check 3: no wildcard CORS
        if "*" in self.CORS_ORIGINS:
            errors.append(
                "Refusing to start: CORS_ORIGINS contains '*' which is not "
                "allowed in staging/production. List explicit origins instead."
            )

        # Check 4: BASE_DOMAIN required for Host-subdomain tenant resolution
        if not self.BASE_DOMAIN.strip():
            errors.append(
                "IDENTITY_BASE_DOMAIN is required in staging/production so "
                "tenant subdomains (e.g. acme.skyrict.com) can be resolved "
                "from the Host header."
            )

        if errors:
            raise RuntimeError(
                "Production safety check failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        return self


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings populates from env
