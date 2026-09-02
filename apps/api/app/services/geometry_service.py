from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.config import settings
from app.domain.models import Document, TwinEntity
from app.services.object_storage import storage


def _flatten3(values: list[float]) -> list[list[float]]:
    return [values[i:i + 3] for i in range(0, len(values), 3)]


def _proxy_box(entity: TwinEntity, index: int) -> dict[str, Any]:
    """Deterministic geometry fallback when IfcOpenShell geometry is unavailable.

    The fallback is deliberately marked as proxy geometry in the API response. It
    preserves entity identity and 4D interaction so the product can run without
    native IFC geometry dependencies, but it is never represented as exact IFC
    geometry.
    """
    digest = hashlib.sha256((entity.external_ids.get("ifcGuid") or entity.id).encode()).digest()
    col = index % 8
    row = (index // 8) % 6
    layer = index // 48
    x = (col - 3.5) * 2.6
    z = (row - 2.5) * 2.5
    y = 0.65 + layer * 1.7
    typ = (entity.external_ids.get("ifcType") or "").upper()
    if "BEAM" in typ or "MEMBER" in typ:
        size = [2.2, 0.28, 0.34]
    elif "COLUMN" in typ or "PILE" in typ:
        size = [0.38, 2.4, 0.38]
        y += 0.7
    elif "SLAB" in typ or "ROOF" in typ:
        size = [2.3, 0.18, 2.0]
    elif "WALL" in typ:
        size = [2.2, 1.9, 0.18]
        y += 0.55
    else:
        size = [0.85, 0.85, 0.85]
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "ifc_guid": entity.external_ids.get("ifcGuid"),
        "ifc_type": entity.external_ids.get("ifcType"),
        "mode": "proxy-box",
        "transform": {"position": [x, y, z], "rotation": [0, 0, 0], "scale": size},
        "vertices": [],
        "indices": [],
    }


def _ifc_exact_geometry(path: str, entities_by_guid: dict[str, TwinEntity], max_triangles_per_entity: int = 120_000) -> list[dict[str, Any]]:
    import ifcopenshell
    import ifcopenshell.geom

    model = ifcopenshell.open(path)
    settings = ifcopenshell.geom.settings()
    try:
        settings.set(settings.USE_WORLD_COORDS, True)
    except Exception:
        pass

    meshes: list[dict[str, Any]] = []
    for guid, entity in entities_by_guid.items():
        try:
            product = model.by_guid(guid)
            if not product:
                continue
            shape = ifcopenshell.geom.create_shape(settings, product)
            raw_verts = list(shape.geometry.verts)
            raw_faces = list(shape.geometry.faces)
            if len(raw_faces) // 3 > max_triangles_per_entity:
                step = max(1, math.ceil((len(raw_faces) // 3) / max_triangles_per_entity))
                tris = _flatten3(raw_faces)[::step]
                raw_faces = [v for tri in tris for v in tri]
            meshes.append({
                "entity_id": entity.id,
                "name": entity.name,
                "ifc_guid": guid,
                "ifc_type": entity.external_ids.get("ifcType"),
                "mode": "ifc-exact",
                "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
                "vertices": raw_verts,
                "indices": raw_faces,
            })
        except Exception:
            continue
    return meshes


def geometry_for_model(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    document_id: str,
    entity_ids: set[str] | None = None,
    max_triangles_per_entity: int = 120_000,
) -> dict[str, Any]:
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.project_id == project_id,
            Document.tenant_id == ctx.tenant_id,
            Document.organization_id == ctx.organization_id,
            Document.doc_type == "ifc_model",
        )
        .first()
    )
    if not doc:
        raise ValueError("IFC model not found")

    entities = (
        db.query(TwinEntity)
        .filter(TwinEntity.project_id == project_id, TwinEntity.tenant_id == ctx.tenant_id, TwinEntity.organization_id == ctx.organization_id)
        .all()
    )
    entities = [e for e in entities if (e.external_ids or {}).get("modelDocumentId") == document_id]
    if entity_ids is not None:
        entities = [e for e in entities if e.id in entity_ids]
    by_guid = {(e.external_ids or {}).get("ifcGuid"): e for e in entities if (e.external_ids or {}).get("ifcGuid")}

    exact: list[dict[str, Any]] = []
    path = Path(doc.uri)
    source_key = (doc.meta or {}).get("source_object_key")
    if (not path.exists()) and source_key:
        cached = settings.asset_work_path / "source-cache" / f"{(doc.meta or {}).get('sha256') or doc.id}.ifc"
        path = storage.materialize(source_key, cached)
    # Why a mesh is a proxy matters: "the library is missing" is a deployment problem an
    # operator must act on, while "this element carries no geometry" is a property of the
    # model. Telling them to install a library that is already installed sends them to fix
    # something that is not broken.
    triangulation_available = True
    triangulation_error: str | None = None
    try:
        import ifcopenshell.geom  # noqa: F401
    except Exception as exc:
        triangulation_available = False
        triangulation_error = str(exc)

    if path.exists() and by_guid and triangulation_available:
        try:
            exact = _ifc_exact_geometry(str(path), by_guid, max_triangles_per_entity=max_triangles_per_entity)
        except Exception as exc:
            triangulation_error = str(exc)
            exact = []

    exact_ids = {m["entity_id"] for m in exact}
    proxy_entities = [entity for entity in entities if entity.id not in exact_ids]
    proxy = [_proxy_box(entity, index) for index, entity in enumerate(proxy_entities)]
    meshes = exact + proxy

    # Site, building and storey are containers; they have no body geometry by definition
    # and their proxies are not a gap in the model.
    SPATIAL = {"site", "building", "storey", "space"}
    spatial_proxies = sum(1 for entity in proxy_entities if (entity.entity_type or "").lower() in SPATIAL)
    element_proxies = len(proxy_entities) - spatial_proxies

    if not triangulation_available:
        disclaimer = (
            "Exact IFC triangulation is unavailable in this deployment; every mesh is semantic "
            "proxy geometry. Build the image with INSTALL_IFC=true to enable it."
            + (f" ({triangulation_error})" if triangulation_error else "")
        )
    elif triangulation_error:
        disclaimer = f"Triangulation failed for this model, so proxy geometry is shown: {triangulation_error}"
    elif element_proxies:
        disclaimer = (
            f"{element_proxies} element(s) carry no geometric representation in this IFC and are shown "
            "as proxy boxes. This is a property of the model, not of the deployment."
        )
    else:
        disclaimer = None

    return {
        "model_document_id": doc.id,
        "title": doc.title,
        "source_sha256": (doc.meta or {}).get("sha256"),
        # Spatial containers never carry geometry, so a model whose every *element* is
        # triangulated reports as exact even though the site node is a proxy.
        "geometry_mode": (
            "ifc-exact" if exact and not element_proxies
            else ("hybrid" if exact else "semantic-proxy")
        ),
        "triangulation_available": triangulation_available,
        "exact_meshes": len(exact),
        "proxy_meshes": len(proxy),
        "element_proxies": element_proxies,
        "spatial_proxies": spatial_proxies,
        "mesh_count": len(meshes),
        "meshes": meshes,
        "disclaimer": disclaimer,
    }
