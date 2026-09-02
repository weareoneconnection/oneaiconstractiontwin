"""OIDC access-token validation and claim mapping.

These tests sign real RS256 tokens with a throwaway key and stub the JWKS lookup, so
the provider-facing code path is exercised without running an identity provider. What
they pin down is the part that actually breaks in integrations: which claims carry the
tenant scope, how roles are read, and that expiry/audience/issuer are enforced.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings
from app.main import app

ISSUER = "https://idp.example.com/realms/oneai"
AUDIENCE = "construction-twin-api"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(**overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-42",
        "email": "planner@example.com",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "tenant_id": "acme-tenant",
        "organization_id": "acme-org",
        "realm_access": {"roles": ["offline_access", "planner"]},
    }
    claims.update(overrides)
    for key, value in list(claims.items()):
        if value is None:
            claims.pop(key)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def oidc_mode(monkeypatch):
    """Point the app at our fake issuer and short-circuit the JWKS fetch."""
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_audience", AUDIENCE)
    monkeypatch.setattr(settings, "oidc_tenant_claim", "tenant_id")
    monkeypatch.setattr(settings, "oidc_organization_claim", "organization_id")
    monkeypatch.setattr(settings, "oidc_default_tenant", "")
    monkeypatch.setattr(settings, "oidc_default_organization", "")

    class FakeSigningKey:
        key = _PRIVATE_KEY.public_key()

    class FakeJWKClient:
        def get_signing_key_from_jwt(self, _token):
            return FakeSigningKey()

    original_client = security._jwk_client
    original_client.cache_clear()
    security.discovery_document.cache_clear()
    monkeypatch.setattr(security, "_jwk_client", lambda: FakeJWKClient())
    yield
    original_client.cache_clear()
    security.discovery_document.cache_clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_establishes_tenant_scope_and_role():
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers=bearer(make_token()))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tenant_id"] == "acme-tenant"
        assert body["organization_id"] == "acme-org"
        assert body["user_id"] == "user-42"
        assert body["auth_source"] == "oidc"
        # Keycloak puts roles in realm_access; unknown roles are ignored, not fatal.
        assert body["role"] == "planner"
        assert "project:read" in body["permissions"]


def test_unknown_roles_fall_back_to_viewer_rather_than_failing_open():
    with TestClient(app) as client:
        token = make_token(realm_access={"roles": ["some-corporate-group"]})
        body = client.get("/api/v1/auth/me", headers=bearer(token)).json()
        assert body["role"] == "viewer"
        assert body["permissions"] == ["project:read", "twin:read"]


def test_expired_token_is_rejected():
    expired = datetime.now(timezone.utc) - timedelta(minutes=5)
    with TestClient(app) as client:
        token = make_token(exp=int(expired.timestamp()))
        response = client.get("/api/v1/auth/me", headers=bearer(token))
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()


def test_token_for_another_audience_is_rejected():
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers=bearer(make_token(aud="some-other-api")))
        assert response.status_code == 401


def test_token_from_another_issuer_is_rejected():
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers=bearer(make_token(iss="https://evil.example.com")))
        assert response.status_code == 401


def test_missing_tenant_claim_is_refused_with_configuration_guidance():
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me", headers=bearer(make_token(tenant_id=None)))
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert "tenant" in detail.lower()
        assert "OIDC_DEFAULT_TENANT" in detail


def test_single_tenant_deployments_can_supply_defaults(monkeypatch):
    monkeypatch.setattr(settings, "oidc_default_tenant", "solo-tenant")
    monkeypatch.setattr(settings, "oidc_default_organization", "solo-org")
    with TestClient(app) as client:
        body = client.get(
            "/api/v1/auth/me", headers=bearer(make_token(tenant_id=None, organization_id=None))
        ).json()
        assert body["tenant_id"] == "solo-tenant"
        assert body["organization_id"] == "solo-org"


def test_custom_claim_names_are_honoured(monkeypatch):
    monkeypatch.setattr(settings, "oidc_tenant_claim", "https://oneai.dev/tenant")
    monkeypatch.setattr(settings, "oidc_organization_claim", "custom.org")
    with TestClient(app) as client:
        token = make_token(
            tenant_id=None,
            organization_id=None,
            **{"https://oneai.dev/tenant": "claim-tenant", "custom": {"org": "claim-org"}},
        )
        body = client.get("/api/v1/auth/me", headers=bearer(token)).json()
        assert body["tenant_id"] == "claim-tenant"
        assert body["organization_id"] == "claim-org"


def test_tenant_isolation_holds_for_oidc_identities():
    """A token is not a bypass: cross-tenant reads must still 404."""
    with TestClient(app) as client:
        admin = make_token(tenant_id="tenant-one", organization_id="org-one", realm_access={"roles": ["platform_admin"]})
        created = client.post(
            "/api/v1/projects", headers=bearer(admin), json={"name": "OIDC scoped", "code": "OIDC-1"}
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]

        outsider = make_token(tenant_id="tenant-two", organization_id="org-two", realm_access={"roles": ["platform_admin"]})
        assert client.get(f"/api/v1/projects/{project_id}", headers=bearer(outsider)).status_code == 404
        assert client.get(f"/api/v1/projects/{project_id}", headers=bearer(admin)).status_code == 200


def test_auth_config_advertises_the_provider_without_secrets(monkeypatch):
    monkeypatch.setattr(settings, "oidc_client_id", "construction-twin-web")
    # enterprise.py imported the symbol directly, so patch it where it is used.
    from app.api.routes import enterprise

    monkeypatch.setattr(
        enterprise,
        "discovery_document",
        lambda: {
            "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
            "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
            "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
        },
    )
    with TestClient(app) as client:
        body = client.get("/api/v1/auth/config").json()
        assert body["auth_mode"] == "oidc"
        assert body["oidc"]["client_id"] == "construction-twin-web"
        assert body["oidc"]["authorization_endpoint"].endswith("/auth")
        assert body["oidc"]["discovered"] is True
        # Nothing confidential may appear here - the endpoint is unauthenticated.
        assert "secret" not in str(body).lower()


def test_production_requires_a_client_id_for_the_browser_flow():
    """Without a client id the SPA cannot start a sign-in.

    Since production also forbids development header auth, shipping without it would
    lock every user out of a deployment that otherwise looks correctly configured.
    """
    from app.core.config import Settings

    base = dict(
        app_env="production",
        auth_mode="oidc",
        allow_dev_header_auth=False,
        jwt_secret="x" * 40,
        force_https=True,
        demo_endpoints_enabled=False,
        cors_origins="https://twin.example.com",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
    )
    with pytest.raises(ValueError, match="OIDC_CLIENT_ID"):
        Settings(**base)

    configured = Settings(**base, oidc_client_id="construction-twin-web")
    assert configured.is_production


def test_the_token_issuing_script_refuses_the_development_secret(monkeypatch, capsys):
    """The sign-in page asks for a token; this is the only thing that makes one.

    Signing with the built-in default produces a token no real deployment accepts, so the
    script stops and says which value to supply instead of handing over a token that will
    be rejected at the login screen.
    """
    import importlib

    from app.core.config import settings as live

    monkeypatch.setattr(live, "jwt_secret", "development-only-change-me-32-chars!!")
    monkeypatch.setattr(sys, "argv", ["issue_token.py"])
    module = importlib.import_module("scripts.issue_token")

    assert module.main() == 2
    captured = capsys.readouterr()
    assert "development secret" in captured.err
    assert "JWT_SECRET" in captured.err


def test_an_issued_token_is_accepted_by_the_api():
    """The credential the script produces must actually sign in."""
    import importlib

    from app.core.config import settings as live

    module = importlib.import_module("scripts.issue_token")
    token = module.issue_local_token(
        user_id="script-user",
        tenant_id="script-tenant",
        organization_id="script-org",
        role="planner",
        email=None,
        expires_minutes=15,
    )
    with TestClient(app) as client:
        # jwt mode is what a deployment without an identity provider runs.
        original = live.auth_mode
        live.auth_mode = "jwt"
        try:
            response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        finally:
            live.auth_mode = original
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == "script-user"
    assert body["role"] == "planner"
    assert body["tenant_id"] == "script-tenant"
