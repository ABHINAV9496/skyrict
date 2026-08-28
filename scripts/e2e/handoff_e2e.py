"""E2E: full browser-style auth flow against the running stack.

Seeds a fresh tenant + user in the docker Postgres (reachable at 5433),
then drives the real frontend BFF + backend on localhost:3000 / localhost:8000
exactly like a browser would — including the cross-origin handoff form POST
that previously bounced users back to signin under third-party cookie blocking.

Prerequisites (all running):
  * Docker stack:  docker compose -f infra/docker/docker-compose.yml \\
                             -f infra/docker/docker-compose.dev.yml up -d
  * Identity backend on :8000 (the compose `identity` service).
  * Frontend on :3000: `npm run build && npm run start` in apps/web
    (production build; `npm run dev` also works).

Run:
  uv run --directory services/identity python scripts/e2e/handoff_e2e.py

* `*.localhost` does not resolve on this machine, so every request connects to
  127.0.0.1 with an explicit Host header, and separate httpx clients act as the
  two cookie scopes a real browser keeps (signin origin vs workspace origin).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

os.environ["IDENTITY_DATABASE_URL"] = (
    "postgresql+asyncpg://skyrict:skyrict@127.0.0.1:5433/skyrict_identity"
)

import httpx
import pyotp

from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.security import hash_password
from identity.db.session import async_session_factory
from identity.models.role import RoleModel
from identity.models.tenant import TenantModel
from identity.models.user import UserModel

PORT = 3000
PASSWORD = "E2EPass123!"

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


async def seed(tenant_slug: str, email: str) -> None:
    async with async_session_factory() as session:
        tenant = TenantModel(
            id=uuid.uuid4(),
            name=f"E2E {tenant_slug}",
            slug=tenant_slug,
            is_active=True,
            plan_tier="professional",
        )
        session.add(tenant)
        await session.flush()
        for name, permissions in SYSTEM_ROLE_DEFINITIONS:
            session.add(
                RoleModel(
                    tenant_id=tenant.id,
                    name=name,
                    permissions=list(permissions),
                    is_system_role=True,
                )
            )
        session.add(
            UserModel(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                email=email,
                password_hash=hash_password(PASSWORD),
                full_name="E2E Owner",
                is_active=True,
                is_verified=True,
                mfa_enabled=False,
            )
        )
        await session.commit()


def signin_origin(slug: str) -> str:
    return f"http://{slug}.signin.localhost:{PORT}"


def workspace_origin(slug: str) -> str:
    return f"http://{slug}.localhost:{PORT}"


def totp(secret: str) -> str:
    return pyotp.TOTP(secret).now()


async def main() -> None:
    slug = f"e2e-{int(time.time())}"
    email = f"{slug}@skyrict.dev"

    print(f"== Seeding tenant '{slug}' / {email} ==")
    await seed(slug, email)

    # Browser-equivalent clients: one per origin, each with its own cookie jar.
    headers = {"Host": f"{slug}.signin.localhost:{PORT}"}
    signin = httpx.AsyncClient(base_url="http://127.0.0.1:3000", headers=headers, timeout=30)
    work = httpx.AsyncClient(
        base_url="http://127.0.0.1:3000",
        headers={"Host": f"{slug}.localhost:{PORT}"},
        timeout=30,
    )

    try:
        # 1. First login: MFA not yet enrolled -> mfa_setup + access token + cookie.
        r = await signin.post(
            "/api/auth/login",
            headers={"Origin": signin_origin(slug)},
            json={"email": email, "password": PASSWORD},
        )
        body = r.json()
        check("login -> mfa_setup", r.status_code == 200 and body.get("status") == "mfa_setup", body)
        access_token = body.get("accessToken") or ""

        # 2. Begin MFA enrollment: fetch the secret (dev returns it plaintext).
        r = await signin.post(
            "/api/auth/mfa/setup",
            headers={"Origin": signin_origin(slug), "Authorization": f"Bearer {access_token}"},
        )
        sbody = r.json()
        secret = sbody.get("secret") or ""
        check("mfa setup returns secret", r.status_code == 200 and secret, sbody)

        # 3. Enroll with a valid TOTP code (confirm BFF -> /mfa/verify).
        code = totp(secret)
        r = await signin.post(
            "/api/auth/mfa/confirm",
            headers={"Origin": signin_origin(slug), "Authorization": f"Bearer {access_token}"},
            json={"code": code},
        )
        check("mfa enroll confirm", r.status_code == 200 and r.json().get("ok") is True, r.text)

        # 4. Second login: now MFA is enforced -> mfa_challenge + mfa_token.
        r = await signin.post(
            "/api/auth/login",
            headers={"Origin": signin_origin(slug)},
            json={"email": email, "password": PASSWORD},
        )
        body = r.json()
        check("login -> mfa_challenge", r.status_code == 200 and body.get("status") == "mfa_challenge", body)
        mfa_token = body.get("mfaToken") or ""

        # 5. Verify the TOTP challenge -> authenticated + session cookie set.
        r = await signin.post(
            "/api/auth/mfa/verify",
            headers={"Origin": signin_origin(slug)},
            json={"mfa_token": mfa_token, "code": totp(secret)},
        )
        body = r.json()
        check("mfa challenge verify -> authenticated", r.status_code == 200 and body.get("status") == "authenticated", body)

        # 6. Mint the single-use handoff token on the signin origin.
        r = await signin.post(
            "/api/auth/handoff/mint",
            headers={"Origin": signin_origin(slug)},
            json={"redirect": "/"},
        )
        mbody = r.json()
        check("handoff mint", r.status_code == 200 and mbody.get("token"), mbody)

        # 7. Redeem via a top-level form POST to the WORKSPACE origin (cross-origin).
        r = await work.post(
            "/api/auth/handoff",
            headers={"Origin": signin_origin(slug)},
            data={"token": mbody["token"]},
            follow_redirects=False,
        )
        loc = r.headers.get("location", "")
        set_cookie = r.headers.get("set-cookie", "")
        loc_ok = loc == f"{workspace_origin(slug)}/" or loc.rstrip("/") == workspace_origin(slug)
        check(
            "handoff POST -> 303 PRG to workspace",
            r.status_code == 303 and loc_ok and "skyrict_session" in set_cookie,
            f"status={r.status_code} location={loc}",
        )

        # 8. Follow the 303: the browser lands on the workspace root with the
        #    host-scoped cookie and the dashboard must render (no bounce back).
        #    httpx resolves the absolute Location, so GET the workspace root
        #    directly on the workspace client (Host header already set).
        r = await work.get("/", headers={"Origin": workspace_origin(slug)})
        text = r.text
        check(
            "workspace root renders dashboard (no bounce)",
            r.status_code == 200 and "Skyrict Dashboard" in text,
            f"status={r.status_code}",
        )

        # 9. The pre-handoff signin cookie must NOT be required on the workspace:
        #    a fresh workspace-only browser (no signin cookies) must be logged in
        #    purely via the handoff-established cookie.
        check("dashboard HTML mentions sign-in?", "Your session could not be established" not in text, "")

    finally:
        await signin.aclose()
        await work.aclose()

    failed = [c for c in checks if not c[1]]
    print(f"\n== {len(checks) - len(failed)}/{len(checks)} checks passed ==")
    if failed:
        print("FAILED:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
