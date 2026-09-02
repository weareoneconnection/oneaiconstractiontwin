"""Evidence ingestion: the four site sources the pilot scenario names.

The twin's reasoning quality is bounded by the records it can retrieve, and until now
only two of the six declared inputs had an importer — IFC and the baseline schedule. The
four that actually carry *why something happened* (daily reports, photos, RFI/NCR,
inspections) had to be typed into the database by hand.

Three properties matter more than format coverage here:

* **Deduplication.** Site data is re-sent constantly: the same daily report exported
  twice, a photo uploaded from two phones. Every record is keyed by a content hash, so
  re-importing a file is safe and reports how many rows it skipped.
* **Linkage.** A record that mentions no activity and no element is nearly useless to a
  twin. Each row may reference an activity id or an element GUID, and the reference is
  resolved at import time into `fragment.links` so retrieval can use it.
* **Honest confidence.** A signed inspection record and a free-text narrative are not
  equally reliable, and the retrieval layer already weights evidence by confidence. The
  default per source type encodes that, and an explicit column overrides it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import Activity, Evidence, Project, TwinEntity
from app.services.audit import audit
from app.services.events import emit
from app.services.realtime import hub

DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y",
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
)

#: A formal, signed record is more dependable than a narrative someone typed at the end
#: of a shift. Retrieval already multiplies relevance by confidence, so this shows up in
#: which evidence an answer leans on.
DEFAULT_CONFIDENCE = {
    "inspection": 0.97,
    "ncr": 0.95,
    "rfi": 0.92,
    "delivery_record": 0.94,
    "photo": 0.9,
    "daily_report": 0.88,
}

SOURCE_TYPES = set(DEFAULT_CONFIDENCE) | {"note"}

#: Column aliases, in preference order. Site exports never agree on a header name, and
#: rejecting a file over a column called "Description" instead of "content" is a bad
#: trade for a system whose whole problem is not enough evidence.
COLUMNS: dict[str, tuple[str, ...]] = {
    "source_id": ("source_id", "id", "reference", "ref", "no", "number", "document_id", "报告编号", "编号"),
    "content": ("content", "description", "narrative", "text", "body", "summary", "detail", "details", "内容", "描述"),
    "recorded_at": ("date", "recorded_at", "created_at", "raised_at", "issued_at", "report_date", "日期"),
    "author": ("author", "reported_by", "raised_by", "inspector", "created_by", "记录人"),
    "activity_id": ("activity_id", "activity", "wbs", "task_id", "activity_ref"),
    "entity_guid": ("entity_guid", "ifc_guid", "guid", "element_guid", "element"),
    "zone": ("zone", "area", "location", "storey", "level", "区域"),
    "status": ("status", "state", "result", "outcome", "disposition"),
    "confidence": ("confidence", "reliability"),
    "title": ("title", "subject", "name", "标题"),
}


class IngestError(ValueError):
    """A problem the uploader can fix, phrased so they can fix it."""


#: Every alias claimed by a specific field. Used so the loose identifier match below
#: cannot steal a column that already means something else.
CLAIMED = {alias for aliases in COLUMNS.values() for alias in aliases}

#: Site exports name their reference column anything: report_no, ncr_number, rfi_ref,
#: doc_code. Listing them all is a losing game, so an unclaimed column whose name ends
#: this way is treated as the record's identifier.
IDENTIFIER_SUFFIXES = ("_no", "_number", "_ref", "_id", "_code")


def _normalize(row: dict[str, Any]) -> dict[str, str]:
    return {
        str(key).strip().lower().replace(" ", "_"): ("" if value is None else str(value).strip())
        for key, value in row.items()
        if key
    }


def _pick(row: dict[str, Any], field: str) -> str:
    """Read a value by any of its known column names, case- and space-insensitively."""
    normalized = _normalize(row)
    for alias in COLUMNS[field]:
        value = normalized.get(alias)
        if value:
            return value
    if field == "source_id":
        for key, value in normalized.items():
            if value and key not in CLAIMED and key.endswith(IDENTIFIER_SUFFIXES):
                return value
    return ""


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:len(fmt) + 6], fmt)
        except ValueError:
            continue
    return None


def content_hash(project_id: str, source_type: str, source_id: str, content: str) -> str:
    """Identity of a record: what it is about, not when it was uploaded."""
    payload = f"{project_id}|{source_type}|{source_id.strip().lower()}|{' '.join(content.split()).lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _project(db: Session, ctx: RequestContext, project_id: str) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise IngestError("Project not found")
    return project


def _resolve_links(
    db: Session, ctx: RequestContext, project_id: str, activity_ref: str, entity_ref: str
) -> dict[str, Any]:
    """Turn textual references into real ids, so retrieval can follow them.

    Unresolved references are kept rather than dropped: knowing a record mentions
    activity "A1023" is useful even when that activity has not been imported yet.
    """
    links: dict[str, Any] = {}
    if activity_ref:
        links["activity_ref"] = activity_ref
        activity = db.scalar(
            select(Activity).where(
                Activity.project_id == project_id,
                Activity.tenant_id == ctx.tenant_id,
                Activity.external_id == activity_ref,
            )
        )
        if activity:
            links["activity_id"] = activity.id
            links["activity_name"] = activity.name
    if entity_ref:
        links["entity_ref"] = entity_ref
        entity = db.scalar(
            select(TwinEntity).where(
                TwinEntity.project_id == project_id,
                TwinEntity.tenant_id == ctx.tenant_id,
                TwinEntity.external_ids["ifcGuid"].as_string() == entity_ref,
            )
        )
        if entity:
            links["entity_id"] = entity.id
            links["entity_name"] = entity.name
    return links


def _existing_hashes(db: Session, ctx: RequestContext, project_id: str) -> set[str]:
    rows = db.scalars(
        select(Evidence.hash).where(
            Evidence.project_id == project_id,
            Evidence.tenant_id == ctx.tenant_id,
            Evidence.organization_id == ctx.organization_id,
        )
    ).all()
    return {value for value in rows if value}


def build_record(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    source_type: str,
    row: dict[str, Any],
    index: int,
) -> tuple[Evidence, str] | tuple[None, str]:
    """Return (evidence, reason). `evidence` is None when the row cannot be used."""
    content = _pick(row, "content")
    title = _pick(row, "title")
    status = _pick(row, "status")
    if not content and title:
        content = title
    if not content:
        return None, f"row {index}: no content column (looked for {', '.join(COLUMNS['content'][:4])})"

    source_id = _pick(row, "source_id") or f"{source_type.upper()}-{index}"
    recorded_at = parse_date(_pick(row, "recorded_at"))
    author = _pick(row, "author")
    zone = _pick(row, "zone")
    links = _resolve_links(db, ctx, project_id, _pick(row, "activity_id"), _pick(row, "entity_guid"))

    try:
        confidence = float(_pick(row, "confidence") or DEFAULT_CONFIDENCE.get(source_type, 0.9))
    except ValueError:
        confidence = DEFAULT_CONFIDENCE.get(source_type, 0.9)
    confidence = max(0.0, min(1.0, confidence))

    # Title, status and zone are folded into the retrievable text: BM25 can only match
    # what is in `content`, and a status of "closed" is exactly what someone asks about.
    parts = [content]
    if title and title != content:
        parts.insert(0, title)
    if status:
        parts.append(f"Status: {status}.")
    if zone:
        parts.append(f"Location: {zone}.")
    full_content = " ".join(part.strip() for part in parts if part.strip())

    evidence = Evidence(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        content=full_content,
        confidence=confidence,
        hash=content_hash(project_id, source_type, source_id, full_content),
        fragment={
            "title": title or None,
            "status": status or None,
            "author": author or None,
            "zone": zone or None,
            "recorded_at": recorded_at.isoformat() if recorded_at else None,
            "links": links,
            "ingested_at": utcnow().isoformat(),
            "importer": "csv",
        },
    )
    return evidence, "ok"


def import_evidence_csv(
    db: Session, ctx: RequestContext, project_id: str, source_type: str, raw: bytes
) -> dict[str, Any]:
    _project(db, ctx, project_id)
    if source_type not in SOURCE_TYPES:
        raise IngestError(f"Unsupported source type '{source_type}'. Use one of: {', '.join(sorted(SOURCE_TYPES))}")

    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("The file has no header row, so its columns cannot be identified.")

    seen = _existing_hashes(db, ctx, project_id)
    created: list[Evidence] = []
    duplicates = 0
    skipped: list[str] = []
    linked = 0

    for index, row in enumerate(reader, start=1):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        evidence, reason = build_record(db, ctx, project_id, source_type, row, index)
        if evidence is None:
            if len(skipped) < 20:
                skipped.append(reason)
            continue
        if evidence.hash in seen:
            duplicates += 1
            continue
        seen.add(evidence.hash)
        if evidence.fragment.get("links"):
            linked += 1
        db.add(evidence)
        created.append(evidence)

    db.flush()
    emit(db, "evidence.imported", "project", project_id,
         {"source_type": source_type, "created": len(created), "duplicates": duplicates})
    audit(db, ctx, "evidence.import", "project", project_id, project_id,
          after={"source_type": source_type, "created": len(created), "duplicates": duplicates,
                 "skipped": len(skipped), "linked": linked, "columns": reader.fieldnames})
    db.commit()

    hub.publish(ctx.tenant_id, project_id, "evidence.imported",
                {"source_type": source_type, "created": len(created)})

    return {
        "source_type": source_type,
        "created": len(created),
        "duplicates_skipped": duplicates,
        "unusable_rows": len(skipped),
        "linked_to_project_records": linked,
        "detected_columns": reader.fieldnames,
        # Named explicitly so an uploader can fix the file rather than guess.
        "problems": skipped,
        "evidence_ids": [row.id for row in created[:100]],
    }


def store_photo_evidence(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    object_key: str,
    filename: str,
    caption: str,
    taken_at: datetime | None,
    activity_ref: str = "",
    entity_ref: str = "",
    gps: dict[str, float] | None = None,
    sha256: str = "",
) -> dict[str, Any]:
    """Register an uploaded photo as retrievable evidence.

    A photo the retriever cannot read is not evidence, so the caption, location and the
    records it references are what get indexed; the image itself is delivered separately
    through an authenticated, tenant-scoped endpoint.
    """
    _project(db, ctx, project_id)
    links = _resolve_links(db, ctx, project_id, activity_ref, entity_ref)

    described = caption.strip() or f"Site photograph {filename}"
    when = taken_at or utcnow()
    parts = [described, f"Photograph taken {when.date().isoformat()}."]
    if links.get("activity_name"):
        parts.append(f"Related activity: {links['activity_ref']} {links['activity_name']}.")
    if links.get("entity_name"):
        parts.append(f"Related element: {links['entity_name']}.")
    content = " ".join(parts)

    source_id = f"PHOTO-{(sha256 or object_key)[:10].upper()}"
    digest = content_hash(project_id, "photo", source_id, content)
    existing = db.scalar(
        select(Evidence).where(
            Evidence.project_id == project_id,
            Evidence.tenant_id == ctx.tenant_id,
            Evidence.hash == digest,
        )
    )
    if existing:
        return {"created": False, "duplicate": True, "evidence_id": existing.id, "source_id": existing.source_id}

    evidence = Evidence(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        source_type="photo",
        source_id=source_id,
        content=content,
        confidence=DEFAULT_CONFIDENCE["photo"],
        hash=digest,
        fragment={
            "object_key": object_key,
            "filename": filename,
            "taken_at": when.isoformat(),
            "taken_at_source": "exif" if taken_at else "upload-time",
            "gps": gps,
            "links": links,
            "sha256": sha256,
            "importer": "photo-upload",
            "ingested_at": utcnow().isoformat(),
        },
    )
    db.add(evidence)
    db.flush()
    emit(db, "evidence.photo", "evidence", evidence.id, {"project_id": project_id})
    audit(db, ctx, "evidence.photo.upload", "evidence", evidence.id, project_id,
          after={"filename": filename, "linked": bool(links), "taken_at": when.isoformat()})
    db.commit()
    db.refresh(evidence)
    hub.publish(ctx.tenant_id, project_id, "evidence.imported", {"source_type": "photo", "created": 1})
    return {"created": True, "duplicate": False, "evidence_id": evidence.id, "source_id": source_id,
            "linked": links, "taken_at": when.isoformat()}


def list_evidence(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    source_type: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _project(db, ctx, project_id)
    statement = select(Evidence).where(
        Evidence.project_id == project_id,
        Evidence.tenant_id == ctx.tenant_id,
        Evidence.organization_id == ctx.organization_id,
    )
    if source_type:
        statement = statement.where(Evidence.source_type == source_type)
    rows = db.scalars(statement.order_by(Evidence.created_at.desc()).limit(max(1, min(limit, 1000)))).all()
    if query:
        needle = query.lower()
        rows = [row for row in rows if needle in (row.content or "").lower() or needle in (row.source_id or "").lower()]
    return [
        {
            "id": row.id,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "content": row.content,
            "confidence": row.confidence,
            "fragment": row.fragment or {},
            "created_at": row.created_at,
        }
        for row in rows
    ]


def coverage(db: Session, ctx: RequestContext, project_id: str) -> dict[str, Any]:
    """How well fed the twin is, by source. The honest answer to "can it reason yet"."""
    _project(db, ctx, project_id)
    rows = db.scalars(
        select(Evidence).where(
            Evidence.project_id == project_id,
            Evidence.tenant_id == ctx.tenant_id,
            Evidence.organization_id == ctx.organization_id,
        )
    ).all()
    by_type: dict[str, int] = {}
    linked = 0
    for row in rows:
        by_type[row.source_type] = by_type.get(row.source_type, 0) + 1
        if (row.fragment or {}).get("links"):
            linked += 1
    declared = ["daily_report", "photo", "rfi", "ncr", "inspection"]
    present = [name for name in declared if by_type.get(name)]
    return {
        "total": len(rows),
        "by_source_type": by_type,
        "linked_to_project_records": linked,
        "declared_sources": declared,
        "sources_present": present,
        "sources_missing": [name for name in declared if name not in present],
        "coverage_ratio": round(len(present) / len(declared), 2),
        "note": (
            "Ask Twin can only answer what these records contain. A missing source is a "
            "class of question the twin will correctly refuse to answer."
        ),
    }
