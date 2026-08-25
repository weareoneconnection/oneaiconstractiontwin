from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import RequestContext, _context_from_api_key, _decode_bearer_token, _context_from_claims
from app.core.config import settings
from app.services.realtime import hub

router = APIRouter(prefix="/api/v1", tags=["realtime"])

HEARTBEAT_SECONDS = 25


def _context_for_socket(token: str | None, api_key: str | None, tenant: str | None, organization: str | None, role: str | None) -> RequestContext:
    """Authenticate a WebSocket.

    Browsers cannot attach an Authorization header to a WebSocket handshake, so the
    access token arrives as a query parameter. That is the standard workaround and it is
    acceptable over TLS, but the token does land in proxy access logs - which is why the
    same credential rules still apply and why development header auth is only honoured
    outside production.
    """
    if api_key:
        return _context_from_api_key(api_key)
    if token:
        claims, source = _decode_bearer_token(token)
        return _context_from_claims(claims, source)
    if settings.allow_dev_header_auth and not settings.is_production:
        normalized = (role or "platform_admin").strip().lower().replace("-", "_")
        return RequestContext(
            tenant_id=tenant or "demo-tenant",
            organization_id=organization or "demo-org",
            user_id="websocket-client",
            role=normalized,
            auth_source="headers",
        )
    raise PermissionError("Authentication required")


@router.websocket("/ws/projects/{project_id}")
async def project_events(
    websocket: WebSocket,
    project_id: str,
    token: str | None = Query(default=None),
    api_key: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    organization_id: str | None = Query(default=None),
    role: str | None = Query(default=None),
):
    try:
        ctx = _context_for_socket(token, api_key, tenant_id, organization_id, role)
    except Exception:
        # 1008 = policy violation: the client learns it was rejected, not that the
        # endpoint is missing.
        await websocket.close(code=1008)
        return

    from app.core.security import permissions_for_role

    allowed = permissions_for_role(ctx.role)
    if "*" not in allowed and "project:read" not in allowed:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    queue = await hub.subscribe(ctx.tenant_id, project_id)
    await websocket.send_json(
        {
            "type": "connected",
            "project_id": project_id,
            "cross_replica": hub.cross_replica,
            "note": "Live updates are an accelerator; the client should keep its slow poll as the source of truth.",
        }
    )
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                # Keeps intermediaries from closing an idle connection.
                await websocket.send_json({"type": "heartbeat"})
                continue
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        hub.unsubscribe(ctx.tenant_id, project_id, queue)
