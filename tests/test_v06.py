import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from fastapi.testclient import TestClient

from app.main import app
from app.services.distributed_asset_pipeline import run_until_terminal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _seed_ifc(client: TestClient):
    seeded = client.post("/api/v1/demo/seed").json()
    project_id = seeded["project_id"]
    with open(os.path.join(ROOT, "data", "demo_minimal.ifc"), "rb") as file:
        result = client.post(
            f"/api/v1/projects/{project_id}/bim/import-ifc",
            files={"file": ("demo-v06.ifc", file, "application/octet-stream")},
        )
    assert result.status_code == 200, result.text
    return project_id, result.json()["model_document_id"]


def test_v06_distributed_jobs_cache_objects_and_resume():
    with TestClient(app) as client:
        project_id, document_id = _seed_ifc(client)
        payload = {
            "height": 61.25,
            "partition_max_entities": 2,
            "partition_max_triangles": 100000,
            "compression": "none",
            "force_rebuild": True,
        }
        created = client.post(
            f"/api/v1/projects/{project_id}/bim/models/{document_id}/asset-jobs",
            json=payload,
        )
        assert created.status_code == 200, created.text
        job_id = created.json()["id"]
        completed = run_until_terminal(job_id)
        assert completed.status == "completed", completed.error

        detail = client.get(f"/api/v1/asset-jobs/{job_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["progress"] == 100.0
        assert body["total_partitions"] >= 2
        assert body["completed_partitions"] == body["total_partitions"]
        assert all(part["status"] == "completed" for part in body["partitions"])

        manifest_result = client.get(f"/api/v1/asset-jobs/{job_id}/manifest")
        assert manifest_result.status_code == 200, manifest_result.text
        manifest = manifest_result.json()
        assert manifest["version"] == "0.7.0"
        assert manifest["pipeline"] == "distributed-content-addressed-3dtiles"
        assert manifest["partition_strategy"]["resumable"] is True
        assert manifest["partition_strategy"]["partition_count"] >= 2
        assert manifest["entity_count"] >= 3

        tileset = client.get(manifest["tileset_url"])
        assert tileset.status_code == 200, tileset.text
        assert tileset.json()["asset"]["tilesetVersion"] == "0.7.0"
        first_key = manifest["entities"][0]["lods"][0]["object_key"]
        glb = client.get(f"/api/v1/asset-objects/{first_key}")
        assert glb.status_code == 200
        assert glb.content[:4] == b"glTF"

        events = client.get(f"/api/v1/asset-jobs/{job_id}/events")
        assert events.status_code == 200
        event_types = {row["event_type"] for row in events.json()}
        assert {"job.partitioned", "partition.completed", "job.completed"}.issubset(event_types)

        cached_payload = {**payload, "force_rebuild": False}
        cached = client.post(
            f"/api/v1/projects/{project_id}/bim/models/{document_id}/asset-jobs",
            json=cached_payload,
        )
        assert cached.status_code == 200
        assert cached.json()["status"] == "completed"
        assert cached.json()["cache_hit"] is True

        queued = client.post(
            f"/api/v1/projects/{project_id}/bim/models/{document_id}/asset-jobs",
            json={**payload, "height": 62.5, "force_rebuild": True},
        ).json()
        cancelled = client.post(f"/api/v1/asset-jobs/{queued['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        resumed = client.post(f"/api/v1/asset-jobs/{queued['id']}/resume")
        assert resumed.status_code == 200, resumed.text
        final = run_until_terminal(queued["id"], worker_id="resume-test-worker")
        assert final.status == "completed", final.error
