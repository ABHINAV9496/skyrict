from __future__ import annotations

from skyrict_events.schemas import (
    AuthLoginFailed,
    AuthLoginSuccess,
    MFASuccess,
    RbacRoleGranted,
    RoleGrant,
    SessionCreated,
    TenantCreated,
    TenantProvisioned,
    UserCreated,
)


class TestUserCreated:
    def test_default_event_type(self):
        event = UserCreated(user_id="u-1", email="a@b.com", tenant_id="t-1")
        assert event.event_type == "identity.user.created"
        assert event.user_id == "u-1"
        assert event.email == "a@b.com"


class TestAuthLoginFailed:
    def test_default_reason(self):
        event = AuthLoginFailed(tenant_id="t-1")
        assert event.event_type == "identity.auth.login_failed"
        assert event.reason == "invalid_credentials"


class TestAuthLoginSuccess:
    def test_with_ip(self):
        event = AuthLoginSuccess(user_id="u-1", ip_address="1.2.3.4", tenant_id="t-1")
        assert event.ip_address == "1.2.3.4"


class TestTenantCreated:
    def test_fields(self):
        event = TenantCreated(tenant_id="t-1", name="Acme", slug="acme")
        assert event.name == "Acme"
        assert event.slug == "acme"


class TestTenantProvisioned:
    def test_fields(self):
        grants = [
            RoleGrant(role_id="r-1", role_name="tenant_owner", permissions=["*"], user_id="u-1"),
            RoleGrant(role_id="r-2", role_name="standard_user", permissions=["erp.crm.read"]),
        ]
        event = TenantProvisioned(tenant_id="t-1", slug="acme", role_grants=grants)
        assert event.event_type == "identity.tenant.provisioned"
        assert event.slug == "acme"
        assert event.role_grants[0].permissions == ["*"]
        assert event.role_grants[0].user_id == "u-1"
        assert event.role_grants[1].user_id is None

    def test_round_trip_json(self):
        event = TenantProvisioned(
            tenant_id="t-1",
            slug="acme",
            role_grants=[RoleGrant(role_id="r-1", role_name="owner", permissions=["*"])],
        )
        restored = TenantProvisioned.model_validate_json(event.to_json())
        assert restored.role_grants[0].role_name == "owner"


class TestRbacRoleGranted:
    def test_fields(self):
        event = RbacRoleGranted(
            tenant_id="t-1",
            grant=RoleGrant(
                role_id="r-1",
                role_name="auditor",
                permissions=["erp.inventory.read"],
                user_id="u-1",
                scope_id="t-1",
            ),
        )
        assert event.event_type == "identity.rbac.role_granted"
        assert event.grant.scope_id == "t-1"


class TestSessionCreated:
    def test_fields(self):
        event = SessionCreated(user_id="u-1", session_id="s-1", tenant_id="t-1")
        assert event.session_id == "s-1"


class TestMFASuccess:
    def test_default_method(self):
        event = MFASuccess(user_id="u-1", tenant_id="t-1")
        assert event.method == "totp"
