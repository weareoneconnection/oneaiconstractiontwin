from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient

from app.core.config import settings


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    organization_id: str
    user_id: str
    role: str
    email: str | None = None
    auth_source: str = "headers"
    claims: dict[str, Any] = field(default_factory=dict, compare=False)


ROLE_PERMISSIONS = {
    "platform_admin": {"*"},
    "organization_admin": {
        "project:read", "project:write", "twin:read", "twin:write", "ai:run",
        "action:approve", "audit:read", "admin:read", "user:manage", "comment:write",
    },
    "project_director": {
        "project:read", "project:write", "twin:read", "twin:write", "ai:run",
        "action:approve", "audit:read", "admin:read", "comment:write",
    },
    "project_manager": {
        "project:read", "project:write", "twin:read", "twin:write", "ai:run",
        "action:approve", "audit:read", "comment:write",
    },
    "planner": {"project:read", "twin:read", "twin:write", "ai:run", "audit:read", "comment:write"},
    "qa_qc": {"project:read", "twin:read", "twin:write", "ai:run", "audit:read", "comment:write"},
    "safety": {"project:read", "twin:read", "twin:write", "ai:run", "audit:read", "comment:write"},
    "contractor": {"project:read", "twin:read", "twin:write", "ai:run", "comment:write"},
    "viewer": {"project:read", "twin:read"},
    "ai_agent": {"project:read", "twin:read", "ai:run", "action:propose"},
    # The executor's credential. It reports what it did and files the proof, and
    # that is all: it cannot approve, cannot propose, and cannot read the audit
    # trail. A compromised executor key must not be able to manufacture the
    # approval it would need to act.
    "service_executor": {"project:read", "action:execute", "evidence:write"},
}


def permissions_for_role(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def require(ctx: RequestContext, permission: str) -> None:
    allowed = permissions_for_role(ctx.role)
    if "*" not in allowed and permission not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission}",
        )


def issue_local_token(
    *,
    user_id: str,
    tenant_id: str,
    organization_id: str,
    role: str,
    email: str | None = None,
    expires_minutes: int | None = None,
) -> str:
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"Unknown role: {role}")
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "organization_id": organization_id,
        "role": role,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes or settings.jwt_exp_minutes)).timestamp()),
    }
    if email:
        claims["email"] = email
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _role_from_claims(claims: dict[str, Any]) -> str:
    candidates: list[str] = []
    if isinstance(claims.get("role"), str):
        candidates.append(claims["role"])
    raw_roles = claims.get("roles")
    if isinstance(raw_roles, str):
        candidates.extend(raw_roles.split())
    elif isinstance(raw_roles, list):
        candidates.extend(str(value) for value in raw_roles)
    realm = claims.get("realm_access")
    if isinstance(realm, dict) and isinstance(realm.get("roles"), list):
        candidates.extend(str(value) for value in realm["roles"])
    for candidate in candidates:
        normalized = candidate.strip().lower().replace("-", "_").replace("/", "_")
        if normalized in ROLE_PERMISSIONS:
            return normalized
    return "viewer"


@lru_cache(maxsize=1)
def _discovered_jwks_url() -> str:
    if settings.oidc_jwks_url:
        return settings.oidc_jwks_url
    if not settings.oidc_issuer:
        raise RuntimeError("OIDC issuer is not configured")
    discovery_url = settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    response = httpx.get(discovery_url, timeout=5.0)
    response.raise_for_status()
    jwks_uri = response.json().get("jwks_uri")
    if not jwks_uri:
        raise RuntimeError("OIDC discovery response does not contain jwks_uri")
    return str(jwks_uri)


@lru_cache(maxsize=1)
def discovery_document() -> dict[str, Any]:
    """Cached OpenID discovery document for the configured issuer."""
    if not settings.oidc_issuer:
        raise RuntimeError("OIDC issuer is not configured")
    response = httpx.get(settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=5.0)
    response.raise_for_status()
    return dict(response.json())


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    return PyJWKClient(_discovered_jwks_url(), cache_keys=True, lifespan=300)


def _decode_oidc_token(token: str) -> dict[str, Any]:
    signing_key = _jwk_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=settings.oidc_algorithm_list,
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer.rstrip("/"),
        options={"require": ["exp", "sub"]},
    )


def _decode_local_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "sub", "tenant_id", "organization_id"]},
    )


def _decode_bearer_token(token: str) -> tuple[dict[str, Any], str]:
    try:
        if settings.auth_mode == "oidc":
            return _decode_oidc_token(token), "oidc"
        if settings.auth_mode == "jwt":
            return _decode_local_token(token), "jwt"
        if settings.auth_mode == "hybrid":
            try:
                unverified = jwt.decode(token, options={"verify_signature": False})
                if settings.oidc_issuer and str(unverified.get("iss", "")).rstrip("/") == settings.oidc_issuer.rstrip("/"):
                    return _decode_oidc_token(token), "oidc"
            except Exception:
                pass
            return _decode_local_token(token), "jwt"
        raise HTTPException(status_code=401, detail="Bearer tokens are disabled in header-auth mode")
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Access token expired") from exc
    except (jwt.InvalidTokenError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=401, detail=f"Invalid access token: {exc}") from exc


def _claim(claims: dict[str, Any], *names: str) -> str | None:
    """First non-empty claim among `names`, including one level of nesting.

    Providers put custom claims in different places: top level, inside a namespaced
    object, or under `resource_access`/`attributes`. Only simple dotted paths are
    supported, deliberately - anything more elaborate belongs in a provider mapper.
    """
    for name in names:
        if not name:
            continue
        # Literal key first: namespaced claims such as "https://oneai.dev/tenant"
        # contain dots but are single keys, not paths.
        if claims.get(name):
            return str(claims[name])
        if "." in name:
            node: Any = claims
            for part in name.split("."):
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(part)
            if node:
                return str(node)
    return None


def _context_from_claims(claims: dict[str, Any], auth_source: str) -> RequestContext:
    tenant_id = _claim(claims, settings.oidc_tenant_claim, "tenant_id", "tenant") or settings.oidc_default_tenant
    organization_id = (
        _claim(claims, settings.oidc_organization_claim, "organization_id", "org_id", "organization")
        or settings.oidc_default_organization
    )
    user_id = claims.get("sub") or claims.get("user_id")
    if not tenant_id or not organization_id or not user_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Token is missing the tenant scope. Configure the identity provider to emit "
                f"'{settings.oidc_tenant_claim}' and '{settings.oidc_organization_claim}' claims, "
                "or set OIDC_DEFAULT_TENANT / OIDC_DEFAULT_ORGANIZATION for a single-tenant deployment."
            ),
        )
    return RequestContext(
        tenant_id=str(tenant_id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        role=_role_from_claims(claims),
        email=str(claims["email"]) if claims.get("email") else None,
        auth_source=auth_source,
        claims=claims,
    )



def _context_from_api_key(api_key: str) -> RequestContext:
    try:
        records = json.loads(settings.api_key_records_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="API key configuration is invalid") from exc
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    record = records.get(digest)
    if not isinstance(record, dict):
        raise HTTPException(status_code=401, detail="Invalid API key")
    role = str(record.get("role") or "viewer").lower().replace("-", "_")
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(status_code=403, detail="API key role is invalid")
    tenant_id = record.get("tenant_id")
    organization_id = record.get("organization_id")
    user_id = record.get("user_id") or "service-client"
    if not tenant_id or not organization_id:
        raise HTTPException(status_code=500, detail="API key record is missing tenant scope")
    return RequestContext(
        tenant_id=str(tenant_id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        role=role,
        email=record.get("email"),
        auth_source="api_key",
        claims=record,
    )

def get_context(
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_organization_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> RequestContext:
    if x_api_key:
        return _context_from_api_key(x_api_key)

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Authorization must use Bearer token")
        claims, source = _decode_bearer_token(token)
        return _context_from_claims(claims, source)

    if settings.allow_dev_header_auth and not settings.is_production and settings.auth_mode in {"headers", "hybrid"}:
        role = (x_role or "platform_admin").strip().lower().replace("-", "_")
        if role not in ROLE_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
        return RequestContext(
            tenant_id=x_tenant_id or "demo-tenant",
            organization_id=x_organization_id or "demo-org",
            user_id=x_user_id or "demo-user",
            role=role,
            email=x_user_email,
            auth_source="headers",
            claims={},
        )

    raise HTTPException(status_code=401, detail="Authentication required")
