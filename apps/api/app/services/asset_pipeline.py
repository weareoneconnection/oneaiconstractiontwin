from __future__ import annotations

import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import RequestContext
from app.core.version import PIPELINE_VERSION
from app.domain.models import Document, TwinEntity
from app.services.geometry_service import geometry_for_model

ASSET_ROOT = settings.generated_asset_path

GENERATED_ASSET_URL_PREFIX = "/api/v1/generated-assets"


class AssetAccessDenied(Exception):
    """Raised when a caller requests a generated asset outside its tenant prefix."""


def generated_asset_url(tenant_id: str, project_id: str, document_id: str, *parts: str) -> str:
    tail = "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))
    base = f"{GENERATED_ASSET_URL_PREFIX}/{tenant_id}/{project_id}/{document_id}"
    return f"{base}/{tail}" if tail else base


def resolve_generated_asset(ctx: RequestContext, asset_path: str) -> Path:
    """Resolve a generated-asset request to a real file, enforcing tenant scope.

    Two independent guards: the first path segment must equal the caller's tenant,
    and the resolved absolute path must stay inside ASSET_ROOT. Neither guard alone
    is trusted.
    """
    raw = str(asset_path).replace("\\", "/").lstrip("/")
    parts = PurePosixPath(raw).parts
    if not raw or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid asset path")
    if parts[0] != ctx.tenant_id:
        raise AssetAccessDenied("Cross-tenant asset access denied")
    root = ASSET_ROOT.resolve()
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Invalid asset path")
    return target


def _pad4(data: bytes, fill: bytes = b"\x00") -> bytes:
    rem = len(data) % 4
    return data if rem == 0 else data + fill * (4 - rem)


def _proxy_mesh(transform: dict[str, Any]) -> tuple[list[float], list[int]]:
    sx, sy, sz = (transform.get("scale") or [1.0, 1.0, 1.0])
    px, py, pz = (transform.get("position") or [0.0, 0.0, 0.0])
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    verts = [
        px-hx, py-hy, pz-hz,  px+hx, py-hy, pz-hz,  px+hx, py+hy, pz-hz,  px-hx, py+hy, pz-hz,
        px-hx, py-hy, pz+hz,  px+hx, py-hy, pz+hz,  px+hx, py+hy, pz+hz,  px-hx, py+hy, pz+hz,
    ]
    faces = [
        0,1,2, 0,2,3, 4,6,5, 4,7,6,
        0,4,5, 0,5,1, 1,5,6, 1,6,2,
        2,6,7, 2,7,3, 3,7,4, 3,4,0,
    ]
    return verts, faces


def _bbox(vertices: list[float]) -> dict[str, list[float]]:
    if not vertices:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0], "half": [0.5, 0.5, 0.5]}
    xs, ys, zs = vertices[0::3], vertices[1::3], vertices[2::3]
    mn = [min(xs), min(ys), min(zs)]
    mx = [max(xs), max(ys), max(zs)]
    center = [(mn[i] + mx[i]) / 2.0 for i in range(3)]
    half = [max((mx[i] - mn[i]) / 2.0, 0.001) for i in range(3)]
    return {"min": mn, "max": mx, "center": center, "half": half}


def _box_volume(b: dict[str, list[float]]) -> list[float]:
    cx, cy, cz = b["center"]
    hx, hy, hz = b["half"]
    return [cx, cy, cz, hx, 0, 0, 0, hy, 0, 0, 0, hz]


def _union_bbox(boxes: list[dict[str, list[float]]]) -> dict[str, list[float]]:
    if not boxes:
        return _bbox([])
    mn = [min(b["min"][i] for b in boxes) for i in range(3)]
    mx = [max(b["max"][i] for b in boxes) for i in range(3)]
    center = [(mn[i] + mx[i]) / 2.0 for i in range(3)]
    half = [max((mx[i] - mn[i]) / 2.0, 0.001) for i in range(3)]
    return {"min": mn, "max": mx, "center": center, "half": half}


def _decimate(indices: list[int], factor: int) -> list[int]:
    if factor <= 1 or len(indices) <= 12:
        return indices[:]
    tris = [indices[i:i+3] for i in range(0, len(indices) - 2, 3)]
    kept = tris[::factor]
    return [v for tri in kept for v in tri] or indices[:3]


def _write_glb(path: Path, vertices: list[float], indices: list[int], name: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    vertex_bin = struct.pack("<" + "f" * len(vertices), *vertices) if vertices else b""
    vertex_bin = _pad4(vertex_bin)
    index_offset = len(vertex_bin)
    index_bin = struct.pack("<" + "I" * len(indices), *indices) if indices else b""
    index_bin = _pad4(index_bin)
    bin_blob = vertex_bin + index_bin
    box = _bbox(vertices)
    gltf = {
        "asset": {"version": "2.0", "generator": f"OneAI Construction Twin v{PIPELINE_VERSION}"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(bin_blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vertex_bin), "target": 34962},
            {"buffer": 0, "byteOffset": index_offset, "byteLength": len(index_bin), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0, "componentType": 5126, "count": len(vertices)//3, "type": "VEC3",
                "min": box["min"], "max": box["max"],
            },
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
    }
    json_chunk = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    total_len = 12 + 8 + len(json_chunk) + 8 + len(bin_blob)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    json_header = struct.pack("<I4s", len(json_chunk), b"JSON")
    bin_header = struct.pack("<I4s", len(bin_blob), b"BIN\x00")
    path.write_bytes(header + json_header + json_chunk + bin_header + bin_blob)
    return {"bytes": path.stat().st_size, "triangles": len(indices)//3, "vertices": len(vertices)//3, "bbox": box}


def _entity_mesh(mesh: dict[str, Any]) -> tuple[list[float], list[int]]:
    verts = list(mesh.get("vertices") or [])
    inds = list(mesh.get("indices") or [])
    if not verts or not inds:
        return _proxy_mesh(mesh.get("transform") or {})
    return verts, inds


def _lod_chain(entity_id: str, entity_bbox: dict[str, list[float]]) -> dict[str, Any]:
    bv = {"box": _box_volume(entity_bbox)}
    return {
        "boundingVolume": bv,
        "geometricError": 18.0,
        "refine": "REPLACE",
        "content": {"uri": f"tiles/{entity_id}/lod2.glb"},
        "children": [{
            "boundingVolume": bv,
            "geometricError": 5.0,
            "refine": "REPLACE",
            "content": {"uri": f"tiles/{entity_id}/lod1.glb"},
            "children": [{
                "boundingVolume": bv,
                "geometricError": 0.0,
                "content": {"uri": f"tiles/{entity_id}/lod0.glb"},
            }],
        }],
    }


def build_streaming_assets(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    document_id: str,
    longitude: float = 101.6869,
    latitude: float = 3.1390,
    height: float = 0.0,
) -> dict[str, Any]:
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.project_id == project_id,
        Document.tenant_id == ctx.tenant_id,
        Document.organization_id == ctx.organization_id,
        Document.doc_type == "ifc_model",
    ).first()
    if not doc:
        raise ValueError("IFC model not found")

    geom = geometry_for_model(db, ctx, project_id, document_id)
    model_root = ASSET_ROOT / ctx.tenant_id / project_id / document_id
    tiles_root = model_root / "tiles"
    tiles_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    boxes: list[dict[str, list[float]]] = []
    total_bytes = 0
    for mesh in geom.get("meshes", []):
        entity_id = mesh["entity_id"]
        verts, inds = _entity_mesh(mesh)
        bbox = _bbox(verts)
        boxes.append(bbox)
        lod_stats = []
        for level, factor in ((0, 1), (1, 2), (2, 4)):
            lod_inds = _decimate(inds, factor)
            rel = Path("tiles") / entity_id / f"lod{level}.glb"
            stats = _write_glb(model_root / rel, verts, lod_inds, mesh.get("name") or entity_id)
            total_bytes += stats["bytes"]
            lod_stats.append({"level": level, "uri": rel.as_posix(), **stats})
        records.append({
            "entity_id": entity_id,
            "name": mesh.get("name"),
            "ifc_guid": mesh.get("ifc_guid"),
            "ifc_type": mesh.get("ifc_type"),
            "source_mode": mesh.get("mode"),
            "bbox": bbox,
            "lods": lod_stats,
        })

    root_bbox = _union_bbox(boxes)
    tileset = {
        "asset": {"version": "1.1", "tilesetVersion": PIPELINE_VERSION},
        "geometricError": 500.0,
        "root": {
            "boundingVolume": {"box": _box_volume(root_bbox)},
            "geometricError": 120.0,
            "refine": "REPLACE",
            "children": [_lod_chain(r["entity_id"], r["bbox"]) for r in records],
        },
        "extras": {
            "oneai": {
                "project_id": project_id,
                "model_document_id": document_id,
                "georeference": {"longitude": longitude, "latitude": latitude, "height": height},
            }
        },
    }
    (model_root / "tileset.json").write_text(json.dumps(tileset, indent=2), encoding="utf-8")

    manifest = {
        "version": PIPELINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "model_document_id": document_id,
        "source_sha256": geom.get("source_sha256"),
        "source_geometry_mode": geom.get("geometry_mode"),
        "format": "3D Tiles 1.1 + glTF 2.0 GLB",
        "lod_strategy": "REPLACE hierarchy; LOD0 full, LOD1 ~50% triangles, LOD2 ~25% triangles",
        "georeference": {"longitude": longitude, "latitude": latitude, "height": height},
        "root_bbox": root_bbox,
        "entity_count": len(records),
        "total_asset_bytes": total_bytes,
        "tileset_url": generated_asset_url(ctx.tenant_id, project_id, document_id, "tileset.json"),
        "entities": records,
    }
    (model_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def asset_manifest(ctx: RequestContext, project_id: str, document_id: str) -> dict[str, Any]:
    path = ASSET_ROOT / ctx.tenant_id / project_id / document_id / "manifest.json"
    if not path.exists():
        raise ValueError("Streaming assets not built")
    return json.loads(path.read_text(encoding="utf-8"))


def spatial_query(ctx: RequestContext, project_id: str, document_id: str, minx: float, miny: float, minz: float, maxx: float, maxy: float, maxz: float) -> dict[str, Any]:
    manifest = asset_manifest(ctx, project_id, document_id)
    hits = []
    for item in manifest.get("entities", []):
        b = item["bbox"]
        if not (b["max"][0] < minx or b["min"][0] > maxx or b["max"][1] < miny or b["min"][1] > maxy or b["max"][2] < minz or b["min"][2] > maxz):
            hits.append(item)
    return {"query": {"min": [minx,miny,minz], "max": [maxx,maxy,maxz]}, "count": len(hits), "entities": hits}
