from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.backup import create_backup, restore_backup, verify_backup
from app.services.migrations import migration_status
from app.services.object_storage import storage


def headers(tenant: str, organization: str, role: str = "platform_admin") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Organization-ID": organization,
        "X-User-ID": f"{tenant}-user",
        "X-Role": role,
    }


def test_v07_enterprise_auth_readiness_and_tenant_isolation():
    tenant_a = "v07-tenant-a"
    org_a = "v07-org-a"
    tenant_b = "v07-tenant-b"
    org_b = "v07-org-b"

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "0.7.1"
        assert health.json()["edition"] == "Enterprise Pilot Edition"

        readiness = client.get("/api/v1/admin/readiness", headers=headers(tenant_a, org_a))
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["checks"]["database"]["ok"] is True
        assert readiness.json()["checks"]["migrations"]["ok"] is True
        assert migration_status()["at_head"] is True

        token_response = client.post(
            "/api/v1/auth/dev-token",
            json={
                "user_id": "pilot-admin",
                "tenant_id": tenant_a,
                "organization_id": org_a,
                "role": "project_director",
            },
        )
        assert token_response.status_code == 200, token_response.text
        token = token_response.json()["access_token"]
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        assert me.json()["tenant_id"] == tenant_a
        assert me.json()["organization_id"] == org_a
        assert me.json()["role"] == "project_director"

        created = client.post(
            "/api/v1/projects",
            headers=headers(tenant_a, org_a),
            json={"name": "Enterprise Pilot A", "code": "EP-A", "description": "tenant isolation"},
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]

        own_projects = client.get("/api/v1/projects", headers=headers(tenant_a, org_a))
        foreign_projects = client.get("/api/v1/projects", headers=headers(tenant_b, org_b))
        assert any(row["id"] == project_id for row in own_projects.json())
        assert all(row["id"] != project_id for row in foreign_projects.json())

        foreign_detail = client.get(f"/api/v1/projects/{project_id}", headers=headers(tenant_b, org_b))
        assert foreign_detail.status_code == 404

        audit = client.get(f"/api/v1/projects/{project_id}/audit", headers=headers(tenant_a, org_a))
        assert audit.status_code == 200
        assert any(row["action"] == "project.create" for row in audit.json())

        checklist = client.get("/api/v1/pilot/checklist", headers=headers(tenant_a, org_a))
        assert checklist.status_code == 200
        assert checklist.json()["edition"].startswith("OneAI Construction Twin v0.7.1")


def test_v07_backup_verify_and_restore_roundtrip(tmp_path: Path):
    old_db_url = settings.database_url
    old_backup_root = settings.backup_root
    old_storage_root = storage.local_root
    old_backend = storage.backend

    database = tmp_path / "pilot.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE verification (value TEXT NOT NULL)")
    connection.execute("INSERT INTO verification(value) VALUES ('before-backup')")
    connection.commit()
    connection.close()

    object_root = tmp_path / "objects"
    object_root.mkdir(parents=True)
    (object_root / "proof.txt").write_text("evidence-before-backup", encoding="utf-8")

    try:
        settings.database_url = f"sqlite:///{database}"
        settings.backup_root = str(tmp_path / "backups")
        storage.backend = "local"
        storage.local_root = object_root

        backup = create_backup("pytest")
        verified = verify_backup(backup)
        assert verified["ok"] is True

        connection = sqlite3.connect(database)
        connection.execute("UPDATE verification SET value='after-backup'")
        connection.commit()
        connection.close()
        (object_root / "proof.txt").write_text("changed", encoding="utf-8")

        restore_backup(backup, "RESTORE")

        connection = sqlite3.connect(database)
        restored = connection.execute("SELECT value FROM verification").fetchone()[0]
        connection.close()
        assert restored == "before-backup"
        assert (object_root / "proof.txt").read_text(encoding="utf-8") == "evidence-before-backup"
    finally:
        settings.database_url = old_db_url
        settings.backup_root = old_backup_root
        storage.backend = old_backend
        storage.local_root = old_storage_root
