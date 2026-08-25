"""Comments, exports and the portfolio comparison.

Collaboration and reporting move project data around, so the tests here are mostly
about scope and disclosure: who may write, who may read, what leaves the system, and
whether an export still says that a model is uncalibrated.
"""
from __future__ import annotations

import csv
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

from fastapi.testclient import TestClient

from app.main import app


def headers(tenant: str, organization: str, role: str = "platform_admin") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Organization-ID": organization,
        "X-User-ID": f"{tenant}-{role}",
        "X-Role": role,
    }


def seed(client: TestClient, tenant: str, organization: str) -> str:
    response = client.post("/api/v1/demo/seed", headers=headers(tenant, organization))
    assert response.status_code == 200, response.text
    return response.json()["project_id"]


# ------------------------------------------------------------------ comments


def test_comments_are_threaded_scoped_and_audited():
    tenant, organization = "collab-tenant", "collab-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        created = client.post(
            f"/api/v1/projects/{project_id}/comments",
            headers=head,
            json={"body": "Crane outage confirmed with the subcontractor.", "target_type": "project"},
        )
        assert created.status_code == 200, created.text
        comment = created.json()
        assert comment["author_role"] == "platform_admin"
        assert comment["resolved"] is False

        reply = client.post(
            f"/api/v1/projects/{project_id}/comments",
            headers=head,
            json={"body": "Recovery plan agreed for Zone B.", "parent_id": comment["id"]},
        ).json()
        assert reply["parent_id"] == comment["id"]

        # Threading is one level deep: a reply to a reply attaches to the same thread.
        nested = client.post(
            f"/api/v1/projects/{project_id}/comments",
            headers=head,
            json={"body": "Third message", "parent_id": reply["id"]},
        ).json()
        assert nested["parent_id"] == comment["id"]

        listed = client.get(f"/api/v1/projects/{project_id}/comments", headers=head).json()
        assert len(listed) == 3

        resolved = client.post(
            f"/api/v1/projects/{project_id}/comments/{comment['id']}/resolve",
            headers=head,
            json={"resolved": True},
        ).json()
        assert resolved["resolved"] is True
        assert resolved["resolved_by"] == head["X-User-ID"]

        open_only = client.get(
            f"/api/v1/projects/{project_id}/comments?include_resolved=false", headers=head
        ).json()
        assert all(not row["resolved"] for row in open_only)

        # Creating and resolving are both recorded in the audit chain.
        actions = {row["action"] for row in client.get(f"/api/v1/projects/{project_id}/audit", headers=head).json()}
        assert {"comment.create", "comment.resolve"}.issubset(actions)
        assert client.get("/api/v1/admin/audit/verify", headers=head).json()["ok"] is True


def test_viewers_may_read_comments_but_not_write_them():
    tenant, organization = "collab-role-tenant", "collab-role-org"
    with TestClient(app) as client:
        project_id = seed(client, tenant, organization)
        client.post(
            f"/api/v1/projects/{project_id}/comments",
            headers=headers(tenant, organization),
            json={"body": "Baseline note"},
        )
        viewer = headers(tenant, organization, "viewer")
        assert client.get(f"/api/v1/projects/{project_id}/comments", headers=viewer).status_code == 200
        denied = client.post(f"/api/v1/projects/{project_id}/comments", headers=viewer, json={"body": "nope"})
        assert denied.status_code == 403
        assert "comment:write" in denied.json()["detail"]


def test_comments_do_not_cross_tenants():
    with TestClient(app) as client:
        project_id = seed(client, "comment-owner", "comment-owner-org")
        client.post(
            f"/api/v1/projects/{project_id}/comments",
            headers=headers("comment-owner", "comment-owner-org"),
            json={"body": "Internal note"},
        )
        foreign = client.get(
            f"/api/v1/projects/{project_id}/comments", headers=headers("other-tenant", "other-org")
        )
        assert foreign.status_code == 404


def test_an_empty_comment_is_rejected():
    with TestClient(app) as client:
        head = headers("empty-comment-tenant", "empty-comment-org")
        project_id = seed(client, "empty-comment-tenant", "empty-comment-org")
        response = client.post(f"/api/v1/projects/{project_id}/comments", headers=head, json={"body": "   "})
        assert response.status_code == 422 or response.status_code == 400


# ------------------------------------------------------------------- exports


def test_csv_exports_are_scoped_audited_and_disclose_calibration():
    tenant, organization = "export-tenant", "export-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)
        client.post(f"/api/v1/projects/{project_id}/risks/evaluate", headers=head)

        activities = client.get(f"/api/v1/projects/{project_id}/exports/activities.csv", headers=head)
        assert activities.status_code == 200
        assert activities.headers["content-type"].startswith("text/csv")
        assert "attachment; filename=" in activities.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(activities.text)))
        assert rows[0][0] == "external_id"
        assert len(rows) >= 9  # header plus the seeded schedule

        risks = client.get(f"/api/v1/projects/{project_id}/exports/risks.csv", headers=head)
        risk_rows = list(csv.reader(io.StringIO(risks.text)))
        # A probability column in a spreadsheet must carry its calibration state.
        assert "calibrated" in risk_rows[0]
        assert risk_rows[1][risk_rows[0].index("calibrated")] == "false"

        # Taking data out of the system is itself an audited event.
        exports = [row for row in client.get(f"/api/v1/projects/{project_id}/audit", headers=head).json()
                   if row["action"] == "data.export"]
        assert len(exports) >= 2
        assert {row["after"]["dataset"] for row in exports} >= {"activities", "risks"}


def test_audit_export_requires_the_audit_permission():
    tenant, organization = "export-audit-tenant", "export-audit-org"
    with TestClient(app) as client:
        project_id = seed(client, tenant, organization)
        contractor = headers(tenant, organization, "contractor")  # has project:read, not audit:read
        denied = client.get(f"/api/v1/projects/{project_id}/exports/audit.csv", headers=contractor)
        assert denied.status_code == 403
        allowed = client.get(f"/api/v1/projects/{project_id}/exports/audit.csv", headers=headers(tenant, organization))
        assert allowed.status_code == 200


def test_unknown_export_is_rejected_with_the_available_list():
    with TestClient(app) as client:
        head = headers("export-unknown-tenant", "export-unknown-org")
        project_id = seed(client, "export-unknown-tenant", "export-unknown-org")
        response = client.get(f"/api/v1/projects/{project_id}/exports/salaries.csv", headers=head)
        assert response.status_code == 400
        assert "activities" in response.json()["detail"]


def test_project_report_carries_its_disclosure_and_provenance():
    tenant, organization = "report-tenant", "report-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)
        client.post(f"/api/v1/projects/{project_id}/risks/evaluate", headers=head)

        report = client.get(f"/api/v1/projects/{project_id}/report", headers=head).json()
        assert report["project"]["code"] == "STN02"
        assert report["schedule"]["measured"] >= 8
        assert report["latest_risk"]["exposure"] > 0
        assert "uncalibrated" in report["disclosure"]
        assert report["generated_by"]["role"] == "platform_admin"
        assert report["app_version"]


# ----------------------------------------------------------------- portfolio


def test_portfolio_summary_compares_projects_within_the_tenant():
    tenant, organization = "portfolio-tenant", "portfolio-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        seeded = seed(client, tenant, organization)
        second = client.post(
            "/api/v1/projects", headers=head, json={"name": "Second site", "code": "SITE-2"}
        ).json()["id"]

        summary = client.get("/api/v1/portfolio/summary", headers=head).json()
        ids = {row["id"] for row in summary["projects"]}
        assert {seeded, second}.issubset(ids)
        assert summary["project_count"] >= 2

        seeded_row = next(row for row in summary["projects"] if row["id"] == seeded)
        assert seeded_row["counts"]["activities"] >= 8
        assert seeded_row["schedule"]["late"] >= 1
        # A project with no schedule reports zero rather than an estimate.
        second_row = next(row for row in summary["projects"] if row["id"] == second)
        assert second_row["schedule"]["measured"] == 0
        assert second_row["schedule"]["data_quality"] == "insufficient"

        # Another tenant sees none of it.
        foreign = client.get("/api/v1/portfolio/summary", headers=headers("outsider", "outsider-org")).json()
        assert not {row["id"] for row in foreign["projects"]} & ids
