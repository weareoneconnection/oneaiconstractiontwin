#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the v0.7 Enterprise Pilot end-to-end flow against a live API")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant", default="demo-tenant")
    parser.add_argument("--organization", default="demo-org")
    parser.add_argument("--user", default="pilot-admin")
    parser.add_argument("--role", default="platform_admin")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    headers = {
        "X-Tenant-ID": args.tenant,
        "X-Organization-ID": args.organization,
        "X-User-ID": args.user,
        "X-Role": args.role,
    }
    client = httpx.Client(base_url=args.api.rstrip("/"), headers=headers, timeout=30.0)

    def check(response: httpx.Response, label: str):
        if response.status_code >= 400:
            raise SystemExit(f"{label} failed: {response.status_code} {response.text}")
        print(f"[PASS] {label}")
        return response.json()

    def expect_status(response: httpx.Response, expected: int, label: str):
        if response.status_code != expected:
            raise SystemExit(f"{label} failed: expected {expected}, got {response.status_code} {response.text}")
        print(f"[PASS] {label}")

    def assert_that(condition: bool, label: str, detail: str = ""):
        if not condition:
            raise SystemExit(f"{label} failed. {detail}")
        print(f"[PASS] {label}")

    check(client.get("/health"), "liveness")
    check(client.get("/health/ready"), "readiness")
    # A hardened deployment runs with DEMO_ENDPOINTS_ENABLED=false, which is the
    # point of the flag. Fall back to creating a project through the normal API so
    # the chain can still be validated against production-shaped configuration.
    seed_response = client.post("/api/v1/demo/seed")
    if seed_response.status_code == 404:
        print("[SKIP] demo seed (demo endpoints disabled)")
        created = check(
            client.post(
                "/api/v1/projects",
                json={"name": "E2E Pilot Validation", "code": f"E2E-{int(time.time())}", "description": "created by e2e_pilot.py"},
            ),
            "project creation",
        )
        project_id = created["id"]
    else:
        project_id = check(seed_response, "demo seed")["project_id"]

    with (ROOT / "data" / "demo_minimal.ifc").open("rb") as handle:
        imported = check(
            client.post(
                f"/api/v1/projects/{project_id}/bim/import-ifc",
                files={"file": ("demo.ifc", handle, "application/octet-stream")},
            ),
            "IFC import",
        )
    document_id = imported["model_document_id"]

    with (ROOT / "data" / "demo_schedule.csv").open("rb") as handle:
        check(
            client.post(
                f"/api/v1/projects/{project_id}/schedules/import-csv",
                files={"file": ("schedule.csv", handle, "text/csv")},
            ),
            "schedule import",
        )
    check(client.post(f"/api/v1/projects/{project_id}/mappings/auto?threshold=0.12"), "BIM schedule mapping")

    job = check(
        client.post(
            f"/api/v1/projects/{project_id}/bim/models/{document_id}/asset-jobs",
            json={"partition_max_entities": 2, "compression": "none", "force_rebuild": True},
        ),
        "distributed asset job",
    )
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        current = check(client.get(f"/api/v1/asset-jobs/{job['id']}"), "asset job poll")
        if current["status"] in {"completed", "failed", "cancelled"}:
            if current["status"] != "completed":
                raise SystemExit(json.dumps(current, indent=2, default=str))
            break
        time.sleep(1)
    else:
        raise SystemExit("asset job timed out; start the asset worker")

    check(client.get(f"/api/v1/asset-jobs/{job['id']}/manifest"), "3D Tiles manifest")
    check(client.get(f"/api/v1/projects/{project_id}/timeline"), "4D timeline")
    check(
        client.post(
            f"/api/v1/projects/{project_id}/ask",
            json={"question": "Why is the roof steel work behind schedule?"},
        ),
        "Ask Twin evidence response",
    )
    answer = check(
        client.post(
            f"/api/v1/projects/{project_id}/ask",
            json={"question": "Describe the offshore helipad load certification"},
        ),
        "Ask Twin unmatched question",
    )
    assert_that(
        answer["provisional"] is True and not answer["evidence"],
        "evidence policy: unmatched question is downgraded to provisional",
        json.dumps(answer, default=str)[:400],
    )

    risk = check(client.post(f"/api/v1/projects/{project_id}/risks/evaluate"), "risk evaluation")
    assert_that(
        risk["calibrated"] is False and risk["sample_size"] >= 1,
        "risk result declares its model and sample",
    )
    forecast = check(client.post(f"/api/v1/projects/{project_id}/forecast"), "P10/P50/P90 forecast")
    assert_that(
        forecast["delay_days"]["p10"] <= forecast["delay_days"]["p50"] <= forecast["delay_days"]["p90"],
        "forecast percentiles are ordered",
    )
    assert_that(
        forecast["sample"]["activities_measured"] > 0,
        "forecast is derived from the project schedule",
    )
    check(
        client.post(
            f"/api/v1/projects/{project_id}/simulations",
            json={
                "scenario": "Crane C02 unavailable for 7 days",
                "delay_days": 7,
                "cost_per_day": 60000,
                "recovery_efficiency": 0.65,
            },
        ),
        "scenario simulation",
    )
    action = check(
        client.post(
            f"/api/v1/projects/{project_id}/agents/run",
            json={"agent": "project_director", "task": "Propose schedule recovery action"},
        ),
        "agent recommendation",
    )
    check(client.post(f"/api/v1/actions/{action['id']}/approve"), "human approval")
    audit_rows = check(client.get(f"/api/v1/projects/{project_id}/audit"), "audit retrieval")
    assert_that(all(row["entry_hash"] for row in audit_rows), "every audit entry is hash-chained")
    chain = check(client.get("/api/v1/admin/audit/verify"), "audit chain verification")
    assert_that(chain["ok"] is True, "audit chain verifies", json.dumps(chain, default=str))

    # Security regression gates: generated assets must never be reachable without
    # authorisation, and never across tenants.
    expect_status(
        httpx.get(f"{args.api.rstrip('/')}/assets/{args.tenant}/x/tileset.json", timeout=10.0),
        404,
        "no unauthenticated static asset mount",
    )
    expect_status(
        client.get("/api/v1/generated-assets/some-other-tenant/p/d/tileset.json"),
        403,
        "cross-tenant generated asset access denied",
    )
    status = check(client.get(f"/api/v1/projects/{project_id}/pilot-status"), "pilot status")

    print("\nEnterprise Pilot E2E completed")
    print(json.dumps({"project_id": project_id, "pilot_readiness_score": status["pilot_readiness_score"]}, indent=2))


if __name__ == "__main__":
    main()
