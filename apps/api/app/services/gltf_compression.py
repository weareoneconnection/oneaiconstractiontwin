from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import settings

SUPPORTED = {"none", "auto", "meshopt", "draco"}


def compress_glb(path: str | Path, requested: str) -> dict[str, Any]:
    """Optionally compress a GLB using an installed gltf-transform CLI.

    The distributed pipeline never fails solely because the optional compressor is
    unavailable. The manifest records the requested and applied modes so an
    enterprise deployment can enforce compression as a policy if required.
    """
    path = Path(path)
    requested = (requested or "none").lower().strip()
    if requested not in SUPPORTED:
        raise ValueError(f"Unsupported compression mode: {requested}")
    if requested == "none":
        return {"requested": requested, "applied": "none", "bytes_before": path.stat().st_size, "bytes_after": path.stat().st_size}

    mode = "meshopt" if requested == "auto" else requested
    configured = settings.gltf_transform_bin.strip()
    binary = shutil.which(configured) if configured else None
    if not binary:
        return {
            "requested": requested,
            "applied": "none",
            "bytes_before": path.stat().st_size,
            "bytes_after": path.stat().st_size,
            "warning": f"Optional compressor '{configured or 'gltf-transform'}' is not installed",
        }

    before = path.stat().st_size
    output = path.with_name(path.stem + f".{mode}.tmp.glb")
    cmd = [binary, "optimize", str(path), str(output), "--compress", mode]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            return {
                "requested": requested,
                "applied": "none",
                "bytes_before": before,
                "bytes_after": before,
                "warning": (proc.stderr or proc.stdout or "compression command failed")[-1000:],
            }
        output.replace(path)
        return {
            "requested": requested,
            "applied": mode,
            "bytes_before": before,
            "bytes_after": path.stat().st_size,
        }
    except Exception as exc:
        output.unlink(missing_ok=True)
        return {
            "requested": requested,
            "applied": "none",
            "bytes_before": before,
            "bytes_after": before,
            "warning": str(exc),
        }
