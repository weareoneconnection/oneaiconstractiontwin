"""Regression tests for the v0.7.1 hardening pass.

Each test pins a defect that was found by review and fixed:
unauthenticated asset delivery, decorative evidence retrieval, a mutable audit
trail, a spoofable rate-limit key, and forecasts that ignored the schedule.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.core.config import Settings, settings
from app.db.base import SessionLocal
from app.domain.models import AuditLog
from app.main import app
from app.services.asset_pipeline import AssetAccessDenied, resolve_generated_asset
from app.services.audit import verify_audit_chain
from app.core.security import RequestContext


def headers(tenant: str, organization: str, role: str = "platform_admin") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Organization-ID": organization,
        "X-User-ID": f"{tenant}-user",
        "X-Role": role,
    }


def seed(client: TestClient, tenant: str, organization: str) -> dict:
    response = client.post("/api/v1/demo/seed", headers=headers(tenant, organization))
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- asset delivery


def test_generated_assets_are_never_served_from_a_public_static_mount():
    static_mounts = [
        route for route in app.routes
        if isinstance(route, Mount) and route.path == "/assets"
    ]
    assert static_mounts == [], "generated assets must not be exposed by an unauthenticated mount"

    with TestClient(app) as client:
        assert client.get("/assets/demo-tenant/x/y/tileset.json").status_code == 404


def test_generated_asset_endpoint_rejects_cross_tenant_and_traversal():
    with TestClient(app) as client:
        foreign = client.get(
            "/api/v1/generated-assets/other-tenant/p/d/tileset.json",
            headers=headers("hardening-tenant", "hardening-org"),
        )
        assert foreign.status_code == 403

        viewer_has_no_write_path = client.get(
            "/api/v1/generated-assets/hardening-tenant/p/d/missing.json",
            headers=headers("hardening-tenant", "hardening-org", "viewer"),
        )
        assert viewer_has_no_write_path.status_code == 404  # authorised, simply absent

    ctx = RequestContext(tenant_id="hardening-tenant", organization_id="hardening-org", user_id="u", role="viewer")
    with pytest.raises(ValueError):
        resolve_generated_asset(ctx, "hardening-tenant/../../etc/passwd")
    with pytest.raises(AssetAccessDenied):
        resolve_generated_asset(ctx, "another-tenant/p/d/tileset.json")


# ------------------------------------------------------------ evidence policy


def test_ask_twin_retrieves_evidence_relevant_to_the_question():
    with TestClient(app) as client:
        head = headers("evidence-tenant", "evidence-org")
        project_id = seed(client, "evidence-tenant", "evidence-org")["project_id"]

        crane = client.post(
            f"/api/v1/projects/{project_id}/ask",
            headers=head,
            json={"question": "Was the crane unavailable?"},
        ).json()
        assert crane["evidence"], "a question about the crane must retrieve the crane record"
        assert crane["evidence"][0]["source_id"] == "DR-241"
        assert crane["provisional"] is False

        weld = client.post(
            f"/api/v1/projects/{project_id}/ask",
            headers=head,
            json={"question": "What is the status of the weld quality NCR?"},
        ).json()
        assert weld["evidence"][0]["source_id"] == "NCR-118", "retrieval must depend on the question"

        # Different questions must not return the same fixed evidence set.
        assert crane["evidence"][0]["id"] != weld["evidence"][0]["id"]


def test_ask_twin_downgrades_to_provisional_without_matching_evidence():
    with TestClient(app) as client:
        head = headers("provisional-tenant", "provisional-org")
        project_id = seed(client, "provisional-tenant", "provisional-org")["project_id"]
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask",
            headers=head,
            json={"question": "Describe the helicopter landing pad certification"},
        ).json()
        assert answer["evidence"] == []
        assert answer["provisional"] is True
        assert answer["confidence"] <= 0.4
        assert "provisional" in answer["answer"].lower()


def test_ask_twin_reports_that_no_model_produced_the_answer():
    with TestClient(app) as client:
        head = headers("provenance-tenant", "provenance-org")
        project_id = seed(client, "provenance-tenant", "provenance-org")["project_id"]
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "Why is the roof steel late?"}
        ).json()
        # Without a configured gateway the response must say so, in the payload and in the text.
        assert answer["reasoning"]["model_backed"] is False
        assert answer["reasoning"]["mode"] == "demonstrative-local"
        assert "not the output of a domain-trained model" in answer["answer"]


# ---------------------------------------------------------------- audit chain


def test_audit_chain_verifies_and_detects_tampering():
    tenant, organization = "audit-tenant", "audit-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)["project_id"]
        client.post(f"/api/v1/projects/{project_id}/risks/evaluate", headers=head)
        client.post(f"/api/v1/projects/{project_id}/forecast", headers=head)

        verified = client.get("/api/v1/admin/audit/verify", headers=head)
        assert verified.status_code == 200, verified.text
        assert verified.json()["ok"] is True
        assert verified.json()["entries"] >= 2

    # Silently rewrite a stored audit entry, exactly as a privileged operator could.
    with SessionLocal() as db:
        row = (
            db.query(AuditLog)
            .filter(AuditLog.tenant_id == tenant)
            .order_by(AuditLog.sequence)
            .first()
        )
        row.after = {**(row.after or {}), "confidence": 0.999}
        db.commit()

    with TestClient(app) as client:
        broken = client.get("/api/v1/admin/audit/verify", headers=headers(tenant, organization)).json()
        assert broken["ok"] is False
        assert "hash" in broken["reason"]


def test_audit_chain_detects_a_deleted_entry():
    tenant, organization = "audit-delete-tenant", "audit-delete-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)["project_id"]
        for _ in range(3):
            client.post(f"/api/v1/projects/{project_id}/forecast", headers=head)
        assert client.get("/api/v1/admin/audit/verify", headers=head).json()["ok"] is True

    with SessionLocal() as db:
        rows = db.query(AuditLog).filter(AuditLog.tenant_id == tenant).order_by(AuditLog.sequence).all()
        db.delete(rows[1])
        db.commit()

    with SessionLocal() as db:
        assert verify_audit_chain(db, tenant)["ok"] is False


# ---------------------------------------------------------------- rate limiting


def test_rate_limit_identity_ignores_forwarded_headers_unless_trusted():
    from app.core.middleware import EnterpriseMiddleware

    middleware = EnterpriseMiddleware(app)

    class FakeRequest:
        def __init__(self, headers, path="/api/v1/projects"):
            self.headers = headers
            self.client = type("Client", (), {"host": "10.0.0.1"})()
            self.url = type("Url", (), {"path": path})()

    plain = middleware._rate_limit_key(FakeRequest({}))
    spoofed = middleware._rate_limit_key(FakeRequest({"x-forwarded-for": "1.2.3.4"}))
    assert plain == spoofed, "an untrusted X-Forwarded-For must not reset the quota"

    # The quota is per caller, not per caller-and-path.
    assert middleware._rate_limit_key(FakeRequest({}, "/api/v1/projects")) == middleware._rate_limit_key(
        FakeRequest({}, "/api/v1/other")
    )

    # And the fingerprint is stable, unlike the randomised built-in hash().
    keyed = FakeRequest({"authorization": "Bearer abc.def.ghi"})
    assert middleware._rate_limit_key(keyed) == middleware._rate_limit_key(keyed)


def test_rate_limit_returns_429_and_retry_after():
    original_enabled = settings.rate_limit_enabled
    original_requests = settings.rate_limit_requests
    settings.rate_limit_enabled = True
    settings.rate_limit_requests = 3
    try:
        with TestClient(app) as client:
            head = headers("ratelimit-tenant", "ratelimit-org")
            statuses = [client.get("/api/v1/projects", headers=head).status_code for _ in range(6)]
            assert 429 in statuses, statuses
            limited = client.get("/api/v1/projects", headers=head)
            assert limited.status_code == 429
            assert limited.headers["Retry-After"]
            assert limited.headers["X-Request-ID"]
            # Health probes must never be rate limited: a limiter that starves the
            # liveness probe takes the service down by itself.
            assert client.get("/health").status_code == 200
    finally:
        settings.rate_limit_enabled = original_enabled
        settings.rate_limit_requests = original_requests


# ------------------------------------------------------- forecast and risk basis


def test_forecast_is_driven_by_activity_variance_and_flags_thin_data():
    with TestClient(app) as client:
        head = headers("forecast-tenant", "forecast-org")
        project_id = seed(client, "forecast-tenant", "forecast-org")["project_id"]
        forecast = client.post(f"/api/v1/projects/{project_id}/forecast", headers=head).json()

        assert forecast["sample"]["activities_measured"] >= 8
        assert forecast["calibrated"] is False
        assert forecast["drivers"], "late activities must be reported as the forecast drivers"
        assert forecast["drivers"][0]["activity"].startswith("A10")
        # Eight activities is not a calibrated history and the response must say so.
        assert forecast["warning"]
        assert forecast["delay_days"]["p10"] <= forecast["delay_days"]["p50"] <= forecast["delay_days"]["p90"]


def test_forecast_without_a_schedule_declares_insufficient_history():
    with TestClient(app) as client:
        head = headers("empty-tenant", "empty-org")
        created = client.post(
            "/api/v1/projects", headers=head, json={"name": "No schedule", "code": "NS-1"}
        ).json()
        forecast = client.post(f"/api/v1/projects/{created['id']}/forecast", headers=head).json()
        assert forecast["sample"]["activities_measured"] == 0
        assert "insufficient" in forecast["basis"]
        assert forecast["confidence"] <= 0.3


def test_risk_is_derived_from_the_schedule_not_a_constant():
    with TestClient(app) as client:
        head = headers("risk-tenant", "risk-org")
        project_id = seed(client, "risk-tenant", "risk-org")["project_id"]
        risk = client.post(f"/api/v1/projects/{project_id}/risks/evaluate", headers=head).json()
        assert risk["sample_size"] >= 8
        assert risk["calibrated"] is False
        assert any("A10" in cause for cause in risk["causes"])
        assert risk["mitigations"][0]["basis"]


def test_agent_recommendation_is_grounded_and_requires_approval():
    with TestClient(app) as client:
        head = headers("agent-tenant", "agent-org")
        project_id = seed(client, "agent-tenant", "agent-org")["project_id"]
        action = client.post(
            f"/api/v1/projects/{project_id}/agents/run",
            headers=head,
            json={"agent": "project_director", "task": "Propose mitigation"},
        ).json()
        assert action["status"] == "pending_approval"
        assert action["payload"]["grounded_in"]["activities_measured"] >= 8
        assert action["payload"]["grounded_in"]["target_activity"]

        denied = client.post(f"/api/v1/actions/{action['id']}/approve", headers=headers("agent-tenant", "agent-org", "viewer"))
        assert denied.status_code == 403

        approved = client.post(f"/api/v1/actions/{action['id']}/approve", headers=head).json()
        assert approved["status"] == "approved"


# -------------------------------------------------------- production guardrails


@pytest.mark.parametrize(
    "overrides",
    [
        {"allow_dev_header_auth": True},
        {"allow_dev_header_auth": False, "jwt_secret": "development-only-change-me-32-chars!!"},
        {"allow_dev_header_auth": False, "jwt_secret": "x" * 40, "force_https": False},
        {"allow_dev_header_auth": False, "jwt_secret": "x" * 40, "force_https": True, "demo_endpoints_enabled": True},
        {"allow_dev_header_auth": False, "jwt_secret": "x" * 40, "force_https": True, "demo_endpoints_enabled": False, "cors_origins": "*"},
    ],
)
def test_production_rejects_insecure_configuration(overrides):
    base = {
        "app_env": "production",
        "auth_mode": "jwt",
        "allow_dev_header_auth": False,
        "jwt_secret": "x" * 40,
        "force_https": True,
        "demo_endpoints_enabled": False,
    }
    with pytest.raises(ValueError):
        Settings(**{**base, **overrides})


def test_production_accepts_a_hardened_configuration():
    hardened = Settings(
        app_env="production",
        auth_mode="jwt",
        allow_dev_header_auth=False,
        jwt_secret="a-real-production-secret-of-sufficient-length",
        force_https=True,
        demo_endpoints_enabled=False,
        cors_origins="https://twin.example.com",
    )
    assert hardened.is_production
    assert hardened.trust_forwarded_for is False, "proxy headers must be opt-in"


def test_demo_endpoints_can_be_disabled():
    original = settings.demo_endpoints_enabled
    settings.demo_endpoints_enabled = False
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/demo/seed", headers=headers("off-tenant", "off-org"))
            assert response.status_code == 404
    finally:
        settings.demo_endpoints_enabled = original


# ------------------------------------------------- distributed pipeline recovery


def _seed_ifc_job(client: TestClient, tenant: str, organization: str) -> str:
    head = headers(tenant, organization)
    project_id = seed(client, tenant, organization)["project_id"]
    path = os.path.join(os.path.dirname(__file__), "..", "data", "demo_minimal.ifc")
    with open(path, "rb") as file:
        imported = client.post(
            f"/api/v1/projects/{project_id}/bim/import-ifc",
            headers=head,
            files={"file": ("lease-test.ifc", file, "application/octet-stream")},
        )
    assert imported.status_code == 200, imported.text
    document_id = imported.json()["model_document_id"]
    created = client.post(
        f"/api/v1/projects/{project_id}/bim/models/{document_id}/asset-jobs",
        headers=head,
        json={"partition_max_entities": 1, "partition_max_triangles": 100000, "force_rebuild": True},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_expired_partition_lease_is_recovered_for_another_worker():
    from datetime import timedelta

    from app.core.time import utcnow
    from app.domain.models import AssetBuildPartition
    from app.services.asset_jobs import (
        claim_job_for_planning,
        claim_partition,
        plan_job,
        recover_stale_leases,
    )

    with TestClient(app) as client:
        job_id = _seed_ifc_job(client, "lease-tenant", "lease-org")

    with SessionLocal() as db:
        job = claim_job_for_planning(db, "worker-a")
        assert job is not None
        plan_job(db, job.id, "worker-a")

        first = claim_partition(db, "worker-a")
        assert first is not None and first.status == "running"

        # worker-a dies mid-partition; its lease expires.
        first.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

        assert recover_stale_leases(db) >= 1
        db.refresh(first)
        assert first.status == "queued"
        assert first.worker_id is None, "a recovered partition must not stay bound to the dead worker"

        # A second worker can now pick the same partition up.
        retaken = claim_partition(db, "worker-b")
        assert retaken is not None
        assert retaken.worker_id == "worker-b"

        # And two workers never hold the same partition at once.
        concurrent = claim_partition(db, "worker-c")
        if concurrent is not None:
            assert concurrent.id != retaken.id

        db.query(AssetBuildPartition).filter(AssetBuildPartition.job_id == job.id).delete()
        db.commit()


def test_a_partition_that_keeps_losing_its_lease_fails_the_job():
    from datetime import timedelta

    from app.core.config import settings as live_settings
    from app.core.time import utcnow
    from app.services.asset_jobs import (
        claim_job_for_planning,
        claim_partition,
        plan_job,
        recover_stale_leases,
    )

    with TestClient(app) as client:
        job_id = _seed_ifc_job(client, "lease-fail-tenant", "lease-fail-org")

    with SessionLocal() as db:
        job = claim_job_for_planning(db, "worker-x")
        plan_job(db, job.id, "worker-x")
        for _ in range(live_settings.asset_job_max_attempts + 1):
            part = claim_partition(db, "worker-x")
            if part is None:
                break
            part.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
            recover_stale_leases(db)
        db.refresh(job)
        assert job.status == "failed"
        assert "lease expired" in (job.error or "").lower()


def test_a_claim_is_only_supported_by_a_record_that_refers_to_it():
    from app.services.intelligence import _supports_activity
    from app.services.schedule_analytics import ActivityVariance

    activity = ActivityVariance(
        activity_id="x",
        external_id="A1030",
        name="Roof painting Zone B",
        slip_days=4.0,
        critical=True,
        total_float_days=0.0,
        percent_complete=10.0,
        state="overrunning",
    )
    assert _supports_activity("Delay logged against A1030 this week", activity)
    assert _supports_activity("Roof painting halted by wind", activity)
    # One generic word in common is not evidence for this activity.
    assert not _supports_activity("Roof decking Zone B released for installation", activity)
    assert not _supports_activity("", activity)
