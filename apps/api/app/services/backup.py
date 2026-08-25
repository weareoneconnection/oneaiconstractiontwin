from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta
from app.core.time import utcnow, utc_iso
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.services.object_storage import storage


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_path(url: str) -> Path:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("Not a SQLite URL")
    value = url[len(prefix):]
    return Path(value).expanduser().resolve()


def _backup_database(destination: Path) -> Path:
    if settings.database_url.startswith("sqlite"):
        source = _sqlite_path(settings.database_url)
        target = destination / "database.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            sqlite3.connect(str(source)).close()
        src = sqlite3.connect(str(source))
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target

    target = destination / "database.dump"
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(target), settings.libpq_database_url],
        check=True,
    )
    return target


def _backup_objects(destination: Path) -> Path:
    target = destination / "objects.tar.gz"
    if storage.backend == "local":
        with tarfile.open(target, "w:gz") as archive:
            if storage.local_root.exists():
                archive.add(storage.local_root, arcname="objects")
        return target

    storage.ensure_bucket()
    with tempfile.TemporaryDirectory(prefix="construction-twin-s3-backup-") as tmp:
        root = Path(tmp) / "objects"
        root.mkdir(parents=True, exist_ok=True)
        paginator = storage._client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                path = root / key
                path.parent.mkdir(parents=True, exist_ok=True)
                storage._client().download_file(settings.s3_bucket, key, str(path))
        with tarfile.open(target, "w:gz") as archive:
            archive.add(root, arcname="objects")
    return target


def create_backup(label: str = "manual") -> Path:
    timestamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    root = settings.backup_path / f"{timestamp}-{label}"
    root.mkdir(parents=True, exist_ok=False)
    database = _backup_database(root)
    objects = _backup_objects(root)
    manifest = {
        "format": "oneai-construction-twin-backup-v1",
        "created_at": utc_iso(),
        "app_version": settings.app_version,
        "database_url_scheme": urlparse(settings.database_url).scheme,
        "storage_backend": storage.backend,
        "database": {"file": database.name, "sha256": _sha256(database), "bytes": database.stat().st_size},
        "objects": {"file": objects.name, "sha256": _sha256(objects), "bytes": objects.stat().st_size},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


def verify_backup(root: Path) -> dict:
    root = root.expanduser().resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    results = {}
    for key in ("database", "objects"):
        path = root / manifest[key]["file"]
        actual = _sha256(path)
        results[key] = {
            "ok": actual == manifest[key]["sha256"],
            "actual": actual,
            "expected": manifest[key]["sha256"],
        }
    return {"ok": all(item["ok"] for item in results.values()), "artifacts": results, "manifest": manifest}


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if destination not in target.parents and target != destination:
            raise ValueError("Unsafe path in backup archive")
    archive.extractall(destination, filter="data")


def restore_backup(root: Path, confirm: str) -> None:
    if confirm != "RESTORE":
        raise ValueError("Restore requires --confirm RESTORE")
    root = root.expanduser().resolve()
    verified = verify_backup(root)
    if not verified["ok"]:
        raise ValueError("Backup checksum verification failed")
    manifest = verified["manifest"]

    db_artifact = root / manifest["database"]["file"]
    if settings.database_url.startswith("sqlite"):
        destination = _sqlite_path(settings.database_url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_artifact, destination)
    else:
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", settings.libpq_database_url, str(db_artifact)],
            check=True,
        )

    objects = root / manifest["objects"]["file"]
    with tempfile.TemporaryDirectory(prefix="construction-twin-restore-") as tmp:
        temp_root = Path(tmp)
        with tarfile.open(objects, "r:gz") as archive:
            _safe_extract(archive, temp_root)
        source = temp_root / "objects"
        if storage.backend == "local":
            if storage.local_root.exists():
                shutil.rmtree(storage.local_root)
            if source.exists():
                shutil.copytree(source, storage.local_root)
            else:
                storage.local_root.mkdir(parents=True, exist_ok=True)
        else:
            storage.ensure_bucket()
            for path in source.rglob("*"):
                if path.is_file():
                    storage._client().upload_file(str(path), settings.s3_bucket, path.relative_to(source).as_posix())


def prune_old_backups() -> list[str]:
    cutoff = utcnow() - timedelta(days=settings.backup_retention_days)
    removed: list[str] = []
    root = settings.backup_path
    if not root.exists():
        return removed
    for path in root.iterdir():
        if path.is_dir() and datetime.utcfromtimestamp(path.stat().st_mtime) < cutoff:
            shutil.rmtree(path)
            removed.append(path.name)
    return removed
