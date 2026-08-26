"""The approve → dispatch → execute → evidence chain.

These tests exist because the failure this chain is designed to prevent is a
quiet one: an action that looks executed but never reached anyone. So most of
what is asserted here is about what the twin refuses to claim.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.integrations.oneai import OneClawAdapter
from app.main import app
from app.services import action_execution


def headers(tenant: str, organization: str, role: str = "platform_admin") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Organization-ID": organization,
        "X-User-ID": f"{tenant}-user",
        "X-Role": role,
    }


def seed_action(client: TestClient, tenant: str, org: str) -> tuple[str, str]:
    project = client.post(
        "/api/v1/projects",
        headers=headers(tenant, org),
        json={"name": "Tower A", "code": "TWR-A", "description": "chain test"},
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]

    action = client.post(
        f"/api/v1/projects/{project_id}/agents/run",
        headers=headers(tenant, org),
        json={"agent": "project_director", "task": "Review schedule"},
    )
    assert action.status_code == 200, action.text
    return project_id, action.json()["id"]


class FakeDispatch:
    """Stands in for OneClaw. Records what it was asked to do."""

    def __init__(self, result: dict[str, Any]):
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def dispatch(monkeypatch):
    fake = FakeDispatch({"dispatched": True, "action_id": "", "task_id": "tsk_1", "task_status": "queued"})
    monkeypatch.setattr(action_execution.oneclaw, "dispatch_notification_sync", fake)
    monkeypatch.setattr(OneClawAdapter, "refusal_reason", lambda self, approved_by: None)
    return fake


def test_approval_without_recipients_does_not_dispatch(dispatch):
    tenant, org = "chain-t1", "chain-o1"
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        approved = client.post(f"/api/v1/actions/{action_id}/approve", headers=headers(tenant, org), json={})
        assert approved.status_code == 200, approved.text
        # An approval is a decision, not a delivery. Nothing was sent, and the
        # action must not pretend otherwise.
        assert approved.json()["status"] == "approved"
        assert not dispatch.calls


def test_approval_with_recipients_dispatches_and_records_task(dispatch):
    tenant, org = "chain-t2", "chain-o2"
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        approved = client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "site@example.com", "role": "steel_subcontractor"}]},
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["status"] == "dispatched"
        assert body["executor"] == "oneclaw"
        assert body["executor_task_id"] == "tsk_1"
        assert body["executed_at"] is None

        # The executor is handed addresses, never the project organisation.
        sent = dispatch.calls[0]
        assert sent["recipients"] == [
            {"kind": "email", "address": "site@example.com", "name": "site@example.com", "role": "steel_subcontractor"}
        ]
        assert sent["approved_by"] == f"{tenant}-user"


def test_invalid_recipient_is_rejected_before_anything_is_sent(dispatch):
    tenant, org = "chain-t3", "chain-o3"
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        response = client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "not-an-address"}]},
        )
        assert response.status_code == 422
        assert "not an email address" in response.text
        assert not dispatch.calls


def test_dispatch_refusal_keeps_the_approval_and_records_the_reason(monkeypatch):
    tenant, org = "chain-t4", "chain-o4"
    fake = FakeDispatch({"dispatched": False, "reason": "OneClaw is not configured in this deployment"})
    monkeypatch.setattr(action_execution.oneclaw, "dispatch_notification_sync", fake)

    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        response = client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # The human's decision stands; only the delivery failed, and it says why.
        assert body["status"] == "dispatch_failed"
        assert "not configured" in body["execution_error"]


def test_execution_report_advances_the_action_and_files_evidence(dispatch):
    tenant, org = "chain-t5", "chain-o5"
    with TestClient(app) as client:
        project_id, action_id = seed_action(client, tenant, org)
        client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )

        report = client.post(
            f"/api/v1/actions/{action_id}/execution",
            headers=headers(tenant, org, role="service_executor"),
            json={
                "outcome": "executed",
                "oneclaw_task_id": "tsk_1",
                "summary": "Notified 1 recipient",
                "receipts": [{"address": "pm@example.com", "status": "delivered", "reference": "<abc@mail>"}],
                "evidence": [{
                    "source_type": "delivery_receipt",
                    "source_id": "<abc@mail>",
                    "content": "Email delivered to pm@example.com at 2026-08-25T10:00:00Z",
                }],
            },
        )
        assert report.status_code == 200, report.text
        assert report.json() == {
            "id": action_id,
            "status": "executed",
            "outcome": "executed",
            "evidence_created": 1,
            "executor_task_id": "tsk_1",
        }

        evidence = client.get(f"/api/v1/projects/{project_id}/evidence", headers=headers(tenant, org))
        assert any(item["source_type"] == "delivery_receipt" for item in evidence.json())


def test_dry_run_never_becomes_executed(dispatch):
    tenant, org = "chain-t6", "chain-o6"
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )
        report = client.post(
            f"/api/v1/actions/{action_id}/execution",
            headers=headers(tenant, org, role="service_executor"),
            json={"outcome": "dry_run", "summary": "Rehearsal only"},
        )
        assert report.status_code == 200, report.text
        # A rehearsal leaves the action where a human left it: approved, unsent.
        assert report.json()["status"] == "approved"


def test_a_repeated_report_does_not_duplicate_evidence(dispatch):
    tenant, org = "chain-t7", "chain-o7"
    payload = {
        "outcome": "executed",
        "summary": "Notified 1 recipient",
        "evidence": [{"source_type": "delivery_receipt", "content": "delivered once"}],
    }
    with TestClient(app) as client:
        project_id, action_id = seed_action(client, tenant, org)
        client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )
        first = client.post(
            f"/api/v1/actions/{action_id}/execution",
            headers=headers(tenant, org, role="service_executor"), json=payload,
        )
        second = client.post(
            f"/api/v1/actions/{action_id}/execution",
            headers=headers(tenant, org, role="service_executor"), json=payload,
        )
        assert first.json()["evidence_created"] == 1
        assert second.json()["evidence_created"] == 0

        evidence = client.get(f"/api/v1/projects/{project_id}/evidence", headers=headers(tenant, org))
        receipts = [item for item in evidence.json() if item["content"] == "delivered once"]
        assert len(receipts) == 1


def test_executor_role_cannot_approve_its_own_work(dispatch):
    tenant, org = "chain-t8", "chain-o8"
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        denied = client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org, role="service_executor"),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )
        # The executor must never be able to manufacture the approval that is the
        # only thing authorising it to act.
        assert denied.status_code == 403


def test_reporting_on_an_unapproved_action_is_refused(dispatch):
    tenant, org = "chain-t9", "chain-o9"
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        response = client.post(
            f"/api/v1/actions/{action_id}/execution",
            headers=headers(tenant, org, role="service_executor"),
            json={"outcome": "executed", "summary": "claiming an unapproved action"},
        )
        assert response.status_code == 409


def test_unconfirmed_actions_are_reported(dispatch, monkeypatch):
    tenant, org = "chain-t10", "chain-o10"
    monkeypatch.setattr(settings, "oneclaw_dispatch_stale_after_seconds", 0)
    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )
        listed = client.get("/api/v1/actions/unconfirmed", headers=headers(tenant, org))
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["actions"]] == [action_id]


def test_collected_evidence_is_stored_once_per_unchanged_source(dispatch):
    tenant, org = "chain-t11", "chain-o11"
    record = {
        "source_type": "supplier_portal",
        "source_id": "https://supplier.example.com/orders/88",
        "content": "Retrieved from Supplier Portal at 2026-08-25T10:00:00Z: steel delivery confirmed for 2026-08-29",
        "metadata": {"host": "supplier.example.com", "httpStatus": 200},
    }
    with TestClient(app) as client:
        project_id, _ = seed_action(client, tenant, org)
        first = client.post(
            f"/api/v1/projects/{project_id}/evidence/ingest",
            headers=headers(tenant, org, role="service_executor"),
            json={"records": [record]},
        )
        second = client.post(
            f"/api/v1/projects/{project_id}/evidence/ingest",
            headers=headers(tenant, org, role="service_executor"),
            json={"records": [record]},
        )
        assert first.status_code == 200, first.text
        assert first.json() == {"project_id": project_id, "created": 1, "submitted": 1}
        # A collector re-running on a schedule against an unchanged source must
        # not grow the evidence table on every pass.
        assert second.json()["created"] == 0

        evidence = client.get(f"/api/v1/projects/{project_id}/evidence", headers=headers(tenant, org))
        matching = [item for item in evidence.json() if item["source_type"] == "supplier_portal"]
        assert len(matching) == 1
        # Collected observations rank below receipts: the twin saw the retrieval,
        # not the fact.
        assert matching[0]["confidence"] == 0.8


def test_evidence_ingest_rejects_an_unknown_project(dispatch):
    tenant, org = "chain-t12", "chain-o12"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects/prj_does_not_exist/evidence/ingest",
            headers=headers(tenant, org, role="service_executor"),
            json={"records": [{"content": "anything"}]},
        )
        assert response.status_code == 404


def test_viewer_cannot_write_evidence(dispatch):
    tenant, org = "chain-t13", "chain-o13"
    with TestClient(app) as client:
        project_id, _ = seed_action(client, tenant, org)
        response = client.post(
            f"/api/v1/projects/{project_id}/evidence/ingest",
            headers=headers(tenant, org, role="viewer"),
            json={"records": [{"content": "unauthorised"}]},
        )
        assert response.status_code == 403


def test_a_callback_that_lands_during_dispatch_is_not_overwritten(monkeypatch):
    """OneClaw's inline queue reports back before dispatch returns.

    This is not a hypothetical: with the inline queue the executor's callback
    commits `executed` while the dispatching request is still in flight. Writing
    the dispatch state afterwards used to clobber it, leaving a delivered action
    reported as unconfirmed — the exact false negative this chain exists to
    prevent.
    """
    tenant, org = "chain-t14", "chain-o14"

    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)

        def dispatch_and_report_inline(**kwargs: Any) -> dict[str, Any]:
            # A separate session, as the real callback request would have.
            from app.db.session import SessionLocal
            from app.core.security import RequestContext

            session = SessionLocal()
            try:
                action_execution.record_execution(
                    session,
                    RequestContext(
                        tenant_id=tenant, organization_id=org,
                        user_id="oneclaw-executor", role="service_executor",
                    ),
                    kwargs["action_id"],
                    outcome="executed",
                    oneclaw_task_id="tsk_inline",
                    summary="reported before dispatch returned",
                    receipts=[{"address": "pm@example.com", "status": "delivered"}],
                    error=None,
                    evidence=[],
                )
            finally:
                session.close()
            return {"dispatched": True, "task_id": "tsk_inline", "task_status": "success"}

        monkeypatch.setattr(action_execution.oneclaw, "dispatch_notification_sync", dispatch_and_report_inline)
        monkeypatch.setattr(OneClawAdapter, "refusal_reason", lambda self, approved_by: None)

        response = client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "executed"
        assert body["executed_at"] is not None
        assert body["executor_task_id"] == "tsk_inline"

        # And it must not appear on the reconciliation list.
        monkeypatch.setattr(settings, "oneclaw_dispatch_stale_after_seconds", 0)
        unconfirmed = client.get("/api/v1/actions/unconfirmed", headers=headers(tenant, org))
        assert action_id not in [item["id"] for item in unconfirmed.json()["actions"]]


def test_reconciliation_sees_every_tenant(dispatch, monkeypatch):
    """The system job is not tenant-scoped, on purpose.

    An operator asking "did anything we sent go unaccounted for" needs one answer
    across the estate. A per-tenant query is one they have to remember to run for
    each tenant, and the one they forget is the one that matters.
    """
    monkeypatch.setattr(settings, "oneclaw_dispatch_stale_after_seconds", 0)
    stuck: list[str] = []

    with TestClient(app) as client:
        for tenant, org in (("recon-t1", "recon-o1"), ("recon-t2", "recon-o2")):
            _, action_id = seed_action(client, tenant, org)
            client.post(
                f"/api/v1/actions/{action_id}/approve",
                headers=headers(tenant, org),
                json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
            )
            stuck.append(action_id)

        from app.db.session import SessionLocal
        from app.services.action_execution import all_stale_dispatched_actions

        session = SessionLocal()
        try:
            found = {item["id"] for item in all_stale_dispatched_actions(session)}
        finally:
            session.close()

        assert set(stuck) <= found

        # A tenant-scoped caller still sees only its own.
        scoped = client.get("/api/v1/actions/unconfirmed", headers=headers("recon-t1", "recon-o1"))
        assert [item["id"] for item in scoped.json()["actions"]] == [stuck[0]]


def test_sync_dispatch_survives_a_worker_thread(monkeypatch):
    """The bug this guards against passed every mocked test and failed in production.

    A FastAPI sync endpoint runs on an anyio worker thread. The dispatch used to
    drive an async httpx client there via asyncio.run, which built an event loop
    with no working networking and failed with an empty error — surfacing as
    "OneClaw unavailable:" with no reason. This exercises the real sync client on
    a real non-main thread against a local stub, with no mock in the path.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import app.core.config as config_module
    from app.integrations.oneai import OneClawAdapter

    received: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", 0))
            received["body"] = self.rfile.read(length)
            received["path"] = self.path
            self.send_response(202)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"tsk_stub","status":"queued"}')

        def log_message(self, *args):  # keep the test quiet
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    monkeypatch.setattr(config_module.settings, "oneclaw_url", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(config_module.settings, "oneclaw_api_key", "test-token")
    monkeypatch.setattr(config_module.settings, "oneclaw_execution_enabled", True)

    adapter = OneClawAdapter()
    result: dict[str, Any] = {}

    def worker():
        # The exact context that broke: a fresh worker thread, not the main one.
        result.update(
            adapter.dispatch_notification_sync(
                action_id="thread-probe",
                project_id="p",
                approved_by="maqing",
                subject="s",
                body="b",
                recipients=[{"kind": "email", "address": "pm@example.com", "name": "PM", "role": "pm"}],
                summary="t",
            )
        )

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=15)
    server.shutdown()

    assert not thread.is_alive(), "dispatch hung on the worker thread"
    assert result.get("dispatched") is True, f"dispatch failed on a worker thread: {result}"
    assert received.get("path") == "/v1/tasks/run"


def test_reconciliation_catches_a_dispatched_action_with_no_timestamp(dispatch, monkeypatch):
    """A dispatched action with a NULL dispatched_at must not be invisible.

    Found in production: older rows reached `dispatched` with dispatched_at unset,
    and the reconciliation filter `dispatched_at < cutoff` dropped them because
    NULL compares false. An action stuck without even a dispatch time is the most
    suspect kind, not one to hide — so NULL now counts as stale.
    """
    tenant, org = "recon-null-t", "recon-null-o"
    monkeypatch.setattr(settings, "oneclaw_dispatch_stale_after_seconds", 900)

    with TestClient(app) as client:
        _, action_id = seed_action(client, tenant, org)
        client.post(
            f"/api/v1/actions/{action_id}/approve",
            headers=headers(tenant, org),
            json={"recipients": [{"kind": "email", "address": "pm@example.com"}]},
        )

        # Force the exact production shape: dispatched, but no timestamp.
        from app.db.session import SessionLocal
        from app.domain.models import AgentAction

        session = SessionLocal()
        try:
            row = session.get(AgentAction, action_id)
            row.status = "dispatched"
            row.dispatched_at = None
            session.commit()
        finally:
            session.close()

        listed = client.get("/api/v1/actions/unconfirmed", headers=headers(tenant, org))
        assert action_id in [item["id"] for item in listed.json()["actions"]]
