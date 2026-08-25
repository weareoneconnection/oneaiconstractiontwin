from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from app.core.security import RequestContext
from app.domain.models import Document, TwinEntity, GraphRelation, OutboxEvent
from app.services.object_storage import storage

PRODUCT_RE = re.compile(
    r"#(?P<step>\d+)\s*=\s*(?P<type>IFC[A-Z0-9_]+)\s*\(\s*'(?P<guid>[^']*)'(?P<body>.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
NAME_RE = re.compile(r",\s*'([^']+)'\s*,")
SUPPORTED_PREFIXES = (
    "IFCWALL", "IFCSLAB", "IFCBEAM", "IFCCOLUMN", "IFCDOOR", "IFCWINDOW",
    "IFCSTAIR", "IFCROOF", "IFCFOOTING", "IFCPILE", "IFCPLATE", "IFCMEMBER",
    "IFCFLOW", "IFCFURNISHING", "IFCSPACE", "IFCBUILDING", "IFCBUILDINGSTOREY",
    "IFCSITE", "IFCELEMENTASSEMBLY",
)

def _entity_type(ifc_type: str) -> str:
    t = ifc_type.upper()
    if t == "IFCSITE": return "site"
    if t == "IFCBUILDING": return "building"
    if t == "IFCBUILDINGSTOREY": return "storey"
    if t == "IFCSPACE": return "space"
    if any(x in t for x in ("FLOW", "FURNISHING")): return "equipment"
    return "element"

def _fallback_parse(text: str, limit: int = 5000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in PRODUCT_RE.finditer(text):
        ifc_type = m.group("type").upper()
        if not ifc_type.startswith(SUPPORTED_PREFIXES):
            continue
        body = m.group("body")
        nm = NAME_RE.search(body)
        name = nm.group(1).strip() if nm and nm.group(1).strip() not in ("$", "") else f"{ifc_type} #{m.group('step')}"
        rows.append({
            "ifc_guid": m.group("guid"),
            "ifc_type": ifc_type,
            "step_id": int(m.group("step")),
            "name": name,
            "properties": {},
            "storey": None,
        })
        if len(rows) >= limit: break
    return rows

def _ifcopenshell_parse(path: str, limit: int = 5000) -> list[dict[str, Any]]:
    import ifcopenshell  # optional dependency
    model = ifcopenshell.open(path)
    rows: list[dict[str, Any]] = []
    products = model.by_type("IfcProduct")
    for p in products:
        if not getattr(p, "GlobalId", None):
            continue
        info = p.get_info(recursive=False)
        typ = p.is_a().upper()
        if typ.startswith(("IFCPROJECT", "IFCGEOMETRIC", "IFCANNOTATION")):
            continue
        storey = None
        try:
            for rel in getattr(p, "ContainedInStructure", []) or []:
                s = getattr(rel, "RelatingStructure", None)
                if s and s.is_a("IfcBuildingStorey"):
                    storey = getattr(s, "Name", None)
                    break
        except Exception:
            pass
        props: dict[str, Any] = {}
        try:
            from ifcopenshell.util.element import get_psets
            raw = get_psets(p, psets_only=False, qtos_only=False)
            for k, v in list(raw.items())[:8]:
                props[k] = v
        except Exception:
            pass
        rows.append({
            "ifc_guid": p.GlobalId,
            "ifc_type": typ,
            "step_id": info.get("id"),
            "name": getattr(p, "Name", None) or f"{p.is_a()} {p.GlobalId}",
            "properties": props,
            "storey": storey,
        })
        if len(rows) >= limit: break
    return rows

def parse_ifc(path: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        rows = _ifcopenshell_parse(path)
        if rows:
            return "ifcopenshell", rows
    except Exception:
        pass
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    return "step-fallback", _fallback_parse(text)

def ingest_ifc(db: Session, ctx: RequestContext, project_id: str, path: str, original_name: str) -> dict[str, Any]:
    parser, rows = parse_ifc(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).name or "model.ifc")
    source_object_key = f"sources/{ctx.tenant_id}/{project_id}/{digest}/{safe_name}"
    storage.put_file(source_object_key, path, "application/x-step")
    doc = Document(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id,
        doc_type="ifc_model", title=original_name, uri=path,
        meta={"sha256": digest, "parser": parser, "element_count": len(rows), "source_object_key": source_object_key, "storage_backend": storage.backend},
    )
    db.add(doc); db.flush()
    created: list[TwinEntity] = []
    for r in rows:
        spatial = {"storey": r.get("storey")} if r.get("storey") else {}
        e = TwinEntity(
            tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id,
            entity_type=_entity_type(r["ifc_type"]), name=r["name"],
            external_ids={"ifcGuid": r["ifc_guid"], "ifcType": r["ifc_type"], "stepId": r.get("step_id"), "modelDocumentId": doc.id},
            spatial=spatial,
            lifecycle={"plannedStatus": "unknown", "actualStatus": "unknown", "progress": 0},
            links={"activities": [], "documents": [doc.id], "evidence": []},
            intelligence={"healthScore": None, "riskScore": None, "aiSummary": "Imported from IFC"},
        )
        db.add(e); created.append(e)
    db.flush()
    for e in created:
        db.add(GraphRelation(
            tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id,
            source_id=e.id, relation="DOCUMENTED_BY", target_id=doc.id,
            meta={"source": "ifc-import"},
        ))
    db.add(OutboxEvent(topic="bim.model.imported", aggregate_type="project", aggregate_id=project_id,
                       payload={"document_id": doc.id, "filename": original_name, "parser": parser, "entities": len(created)}))
    db.commit()
    return {"model_document_id": doc.id, "filename": original_name, "sha256": digest, "parser": parser, "entities_created": len(created), "entity_ids": [e.id for e in created[:100]]}
