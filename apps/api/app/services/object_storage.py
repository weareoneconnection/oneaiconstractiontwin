from __future__ import annotations

import io
import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator

import boto3
from botocore.exceptions import ClientError

from app.core.config import PROJECT_ROOT, settings

DEFAULT_LOCAL_ROOT = PROJECT_ROOT / "data" / "object-store"


def normalize_key(key: str) -> str:
    """Normalize an object key and reject traversal / absolute paths."""
    raw = key.replace("\\", "/").lstrip("/")
    path = PurePosixPath(raw)
    if not raw or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid object key")
    return path.as_posix()


def guess_content_type(key: str) -> str:
    if key.endswith(".glb"):
        return "model/gltf-binary"
    if key.endswith(".gltf"):
        return "model/gltf+json"
    if key.endswith(".ifc"):
        return "application/x-step"
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


@dataclass
class StoredObject:
    key: str
    size: int
    content_type: str


class ObjectStorage:
    def __init__(self) -> None:
        self.backend = settings.asset_storage_backend.lower().strip()
        if self.backend not in {"local", "s3"}:
            raise ValueError("ASSET_STORAGE_BACKEND must be local or s3")
        local = Path(settings.asset_local_root).expanduser() if settings.asset_local_root else DEFAULT_LOCAL_ROOT
        self.local_root = local.resolve()
        self.local_root.mkdir(parents=True, exist_ok=True)
        self._s3 = None
        self._bucket_ready = False

    def _client(self):
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint or None,
                aws_access_key_id=settings.s3_access_key or None,
                aws_secret_access_key=settings.s3_secret_key or None,
                region_name=settings.s3_region,
            )
        return self._s3

    def ensure_bucket(self) -> None:
        """Create the bucket only when it is genuinely missing.

        A least-privilege object-scoped credential (R2 "Object Read & Write", an S3
        policy without s3:ListBucket) is denied `head_bucket` with 403 even though the
        bucket exists and objects are fully usable. Treating every ClientError as
        "missing" made the code attempt a create it is not allowed to perform, turning
        a working configuration into a startup failure.
        """
        if self.backend != "s3" or self._bucket_ready:
            return
        client = self._client()
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
            self._bucket_ready = True
            return
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if status not in (0, 404):
                # 403 and friends: the bucket is there, this credential just cannot
                # inspect it at bucket level. Object operations decide the outcome.
                self._bucket_ready = True
                return
        if settings.s3_region and settings.s3_region != "us-east-1" and not settings.s3_endpoint:
            client.create_bucket(Bucket=settings.s3_bucket, CreateBucketConfiguration={"LocationConstraint": settings.s3_region})
        else:
            client.create_bucket(Bucket=settings.s3_bucket)
        self._bucket_ready = True

    def local_path(self, key: str) -> Path:
        key = normalize_key(key)
        path = (self.local_root / key).resolve()
        if self.local_root not in path.parents and path != self.local_root:
            raise ValueError("Invalid object key")
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> StoredObject:
        key = normalize_key(key)
        content_type = content_type or guess_content_type(key)
        if self.backend == "local":
            path = self.local_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            return StoredObject(key, len(data), content_type)
        self.ensure_bucket()
        self._client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
        return StoredObject(key, len(data), content_type)

    def put_file(self, key: str, source: str | Path, content_type: str | None = None) -> StoredObject:
        key = normalize_key(key)
        source = Path(source)
        content_type = content_type or guess_content_type(key)
        if self.backend == "local":
            path = self.local_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with source.open("rb") as src, tmp.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            tmp.replace(path)
            return StoredObject(key, path.stat().st_size, content_type)
        self.ensure_bucket()
        self._client().upload_file(
            str(source), settings.s3_bucket, key,
            ExtraArgs={"ContentType": content_type},
        )
        return StoredObject(key, source.stat().st_size, content_type)

    def exists(self, key: str) -> bool:
        key = normalize_key(key)
        if self.backend == "local":
            return self.local_path(key).is_file()
        self.ensure_bucket()
        try:
            self._client().head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except ClientError:
            return False

    def size(self, key: str) -> int:
        key = normalize_key(key)
        if self.backend == "local":
            return self.local_path(key).stat().st_size
        self.ensure_bucket()
        result = self._client().head_object(Bucket=settings.s3_bucket, Key=key)
        return int(result.get("ContentLength") or 0)

    def read_bytes(self, key: str) -> bytes:
        key = normalize_key(key)
        if self.backend == "local":
            return self.local_path(key).read_bytes()
        self.ensure_bucket()
        return self._client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()

    def materialize(self, key: str, destination: str | Path) -> Path:
        key = normalize_key(key)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "local":
            source = self.local_path(key)
            if not source.exists():
                raise FileNotFoundError(key)
            if source.resolve() != destination.resolve():
                tmp = destination.with_suffix(destination.suffix + ".tmp")
                with source.open("rb") as src, tmp.open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                tmp.replace(destination)
            return destination
        self.ensure_bucket()
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        self._client().download_file(settings.s3_bucket, key, str(tmp))
        tmp.replace(destination)
        return destination

    def open_local(self, key: str) -> Path | None:
        if self.backend != "local":
            return None
        path = self.local_path(key)
        return path if path.exists() else None

    def get_s3_object(self, key: str):
        key = normalize_key(key)
        if self.backend != "s3":
            raise ValueError("S3 backend is not active")
        self.ensure_bucket()
        return self._client().get_object(Bucket=settings.s3_bucket, Key=key)

    def delete_prefix(self, prefix: str) -> int:
        prefix = normalize_key(prefix)
        deleted = 0
        if self.backend == "local":
            root = self.local_path(prefix)
            if root.is_file():
                root.unlink()
                return 1
            if root.is_dir():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink(); deleted += 1
                    elif path.is_dir():
                        path.rmdir()
                root.rmdir()
            return deleted
        self.ensure_bucket()
        paginator = self._client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix.rstrip("/") + "/"):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if objects:
                self._client().delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": objects})
                deleted += len(objects)
        return deleted

    def healthcheck(self) -> dict[str, object]:
        if self.backend == "local":
            self.local_root.mkdir(parents=True, exist_ok=True)
            probe = self.local_root / ".healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"backend": "local", "root": str(self.local_root)}
        self.ensure_bucket()
        # Probe the capability the application actually needs - write, read back and
        # delete one object under our own prefix - rather than bucket administration.
        probe_key = f"{settings.asset_object_prefix.strip('/')}/.healthcheck"
        client = self._client()
        client.put_object(Bucket=settings.s3_bucket, Key=probe_key, Body=b"ok", ContentType="text/plain")
        client.get_object(Bucket=settings.s3_bucket, Key=probe_key)["Body"].read()
        client.delete_object(Bucket=settings.s3_bucket, Key=probe_key)
        return {"backend": "s3", "bucket": settings.s3_bucket, "probe": "object-read-write"}

    def api_url(self, key: str) -> str:
        return f"/api/v1/asset-objects/{normalize_key(key)}"


storage = ObjectStorage()
