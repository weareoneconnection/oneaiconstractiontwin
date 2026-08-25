from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.core.config import settings


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str | None, fallback: str = "upload.bin") -> str:
    value = Path(filename or fallback).name
    return SAFE_NAME.sub("_", value)[:180] or fallback


def validate_extension(filename: str | None, allowed: set[str] | None = None) -> str:
    suffix = Path(filename or "").suffix.lower()
    allowed = allowed or settings.allowed_extension_set
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or 'none'}")
    return suffix


async def save_upload(
    file: UploadFile,
    destination_dir: Path,
    *,
    allowed: set[str] | None = None,
    fallback_name: str = "upload.bin",
) -> dict[str, object]:
    suffix = validate_extension(file.filename, allowed)
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(file.filename, fallback_name)
    target = destination_dir / f"{uuid4().hex[:12]}_{filename}"
    limit = settings.max_upload_mb * 1024 * 1024
    total = 0
    digest = hashlib.sha256()
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds {settings.max_upload_mb} MB limit",
                    )
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {
        "path": target,
        "filename": filename,
        "suffix": suffix,
        "bytes": total,
        "sha256": digest.hexdigest(),
    }
