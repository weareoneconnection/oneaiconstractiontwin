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
from app.services.tabular import UnreadableFile, read_table
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
    #: A punch list is an outstanding-work record, not a non-conformance: it is a
    #: maintained working document, so it is dependable but revised often.
    "punch_list": 0.93,
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
    "source_id": ("source_id", "id", "reference", "ref", "no", "number", "document_id", "报告编号", "编号", "序号"),
    "content": ("content", "description", "narrative", "text", "body", "summary", "detail", "details",
                "内容", "描述", "问题描述", "备注", "说明"),
    "recorded_at": ("date", "recorded_at", "created_at", "raised_at", "issued_at", "report_date",
                    "日期", "完成安装时间", "完成时间", "检查日期"),
    "author": ("author", "reported_by", "raised_by", "inspector", "created_by", "记录人", "责任人", "人员配置"),
    "activity_id": ("activity_id", "activity", "wbs", "task_id", "activity_ref", "工序编号"),
    "entity_guid": ("entity_guid", "ifc_guid", "guid", "element_guid", "element"),
    "zone": ("zone", "area", "location", "storey", "level", "区域", "部位", "工区", "站点"),
    "status": ("status", "state", "result", "outcome", "disposition", "状态", "整改情况", "完成情况"),
    "confidence": ("confidence", "reliability"),
    "title": ("title", "subject", "name", "标题", "名称", "项目名称", "工作内容"),
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


#: Values that are identifiers or measurements rather than a description of work.
_NOT_DESCRIPTIVE = ("是", "否", "完成", "未完成", "yes", "no", "done", "n/a", "-")


def _longest_text_cell(row: dict[str, Any]) -> tuple[str, str] | None:
    """Best guess at the column holding an item description: (header, value)."""
    # Only columns nothing else claims. An author or a date is not a description of
    # work, and inferring one as the item would produce evidence whose content is a
    # person's name.
    claimed = {alias for field, aliases in COLUMNS.items() if field not in ("content", "title") for alias in aliases}
    best: tuple[str, str] | None = None
    for key, value in _normalize(row).items():
        if not value or key in claimed or key.startswith("column_"):
            continue
        stripped = value.replace(".", "", 1).replace("%", "").replace("/", "")
        if stripped.isdigit() or value.lower() in _NOT_DESCRIPTIVE:
            continue
        if len(value) < 3 or len(value) > 300:
            continue
        if best is None or len(value) > len(best[1]):
            best = (key, value)
    return best


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


#: "RS01消项计划表2026/3/11" → RS01. A punch list's title is where the station lives, and
#: it is the only place: the rows themselves carry a row number and nothing else.
SHEET_LABEL_RE = re.compile(r"^\s*([A-Za-z]{1,4}[-_]?\d{1,3}|[\u4e00-\u9fff]{2,12}(?:站|工区))")


def sheet_context(title_rows: list[str]) -> dict[str, str]:
    """Site identity carried by the sheet title rather than by its rows.

    Without this every punch list row is just "item 3", indistinguishable from item 3 of
    every other station — and a question about one station is answered with another
    station's work. That is a confidently wrong answer, which is worse than no answer.
    """
    for line in title_rows:
        text = (line or "").strip()
        if not text:
            continue
        match = SHEET_LABEL_RE.match(text)
        label = match.group(1) if match else ""
        if not label:
            # Fall back to the leading run before a known document-type word.
            for marker in ("消项", "销项", "清单", "计划表"):
                if marker in text:
                    label = text.split(marker)[0].strip()
                    break
        if label:
            return {"label": label[:24], "title": text[:120]}
    return {"label": "", "title": title_rows[0][:120] if title_rows else ""}


def content_hash(project_id: str, source_type: str, source_id: str, content: str, document: str = "") -> str:
    """Identity of a record: what it is about, and which document it came from.

    The document belongs in the identity. Two stations' punch lists legitimately contain
    an item numbered 1 with the same wording, and without this they would collapse into
    one record — silently losing a station's work. Re-importing the *same* document still
    deduplicates, because its title is the same.
    """
    payload = (
        f"{project_id}|{source_type}|{document.strip().lower()}|"
        f"{source_id.strip().lower()}|{' '.join(content.split()).lower()}"
    )
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
    sheet: dict[str, str] | None = None,
) -> tuple[Evidence, str] | tuple[None, str]:
    """Return (evidence, reason). `evidence` is None when the row cannot be used."""
    content = _pick(row, "content")
    title = _pick(row, "title")
    status = _pick(row, "status")
    if not content and title:
        content = title

    inferred_from = ""
    if not content:
        # No alias list survives contact with real site templates: one project calls the
        # item column 名称, the next 剩余主要工作内容. Rather than reject the row, take the
        # longest free-text cell — which is what an item description looks like — and
        # record which column it came from so the choice is inspectable.
        candidate = _longest_text_cell(row)
        if candidate:
            inferred_from, content = candidate

    if not content:
        # A site template ships with numbered rows waiting to be filled in. Those are not
        # ingestion failures, and reporting them as such makes a clean import look broken.
        filled = {key: value for key, value in _normalize(row).items() if value}
        only_identifier = filled and all(key in COLUMNS["source_id"] for key in filled)
        if only_identifier or not filled:
            return None, "blank"
        return None, (
            f"row {index}: no usable description. Looked for a column named "
            f"{', '.join(COLUMNS['content'][:3])} and found no free text in the row either."
        )

    sheet = sheet or {"label": "", "title": ""}
    raw_id = _pick(row, "source_id") or str(index)
    normalized_id = raw_id[:-2] if raw_id.endswith(".0") else raw_id

    # A document that numbers its own records (DR-302, NCR-118) already has a citable
    # identifier and keeps it. A bare row number does not: "[3]" would mean item 3 of
    # nine different stations, so it is qualified by the sheet it came from.
    is_bare_row_number = normalized_id.replace(".", "", 1).isdigit()
    if not is_bare_row_number:
        source_id = normalized_id
    elif sheet["label"]:
        source_id = f"{sheet['label']}-{normalized_id}"
    else:
        source_id = f"{source_type.upper()}-{normalized_id}"
    recorded_at = parse_date(_pick(row, "recorded_at"))
    author = _pick(row, "author")
    zone = _pick(row, "zone") or sheet["label"]
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

    # Anything else the sheet carries is appended as "label: value". A punch list's
    # meaning lives in columns nobody can enumerate in advance — "材料是/否已下单",
    # "完成安装时间" — and dropping them would leave rows that cannot answer the
    # question they exist to answer.
    normalized = _normalize(row)
    used = {alias for aliases in COLUMNS.values() for alias in aliases}
    extras = [
        f"{key.replace('_', ' ')}: {value}"
        for key, value in normalized.items()
        if value and key not in used and not key.startswith("column_") and len(value) < 120
    ]
    if extras:
        parts.append("(" + "; ".join(extras[:10]) + ")")

    full_content = " ".join(part.strip() for part in parts if part.strip())

    evidence = Evidence(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        content=full_content,
        confidence=confidence,
        hash=content_hash(project_id, source_type, source_id, full_content, sheet["title"]),
        fragment={
            "title": title or None,
            "status": status or None,
            "author": author or None,
            "zone": zone or None,
            "recorded_at": recorded_at.isoformat() if recorded_at else None,
            "sheet_title": sheet["title"] or None,
            "links": links,
            "ingested_at": utcnow().isoformat(),
            "importer": "table",
            # Set when no known column name matched and the description was inferred.
            "content_column_inferred": inferred_from or None,
        },
    )
    return evidence, "ok"


def import_evidence_table(
    db: Session, ctx: RequestContext, project_id: str, source_type: str, raw: bytes, filename: str = "upload.csv"
) -> dict[str, Any]:
    """Import a CSV or Excel export as evidence."""
    _project(db, ctx, project_id)
    if source_type not in SOURCE_TYPES:
        raise IngestError(f"Unsupported source type '{source_type}'. Use one of: {', '.join(sorted(SOURCE_TYPES))}")

    try:
        table = read_table(raw, filename)
    except UnreadableFile as exc:
        raise IngestError(str(exc))

    sheet = sheet_context([" ".join(cell for cell in title if cell) for title in table["title_rows"]])
    seen = _existing_hashes(db, ctx, project_id)
    created: list[Evidence] = []
    duplicates = 0
    skipped: list[str] = []
    blank_rows = 0
    linked = 0

    for index, row in enumerate(table["records"], start=1):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        evidence, reason = build_record(db, ctx, project_id, source_type, row, index, sheet)
        if evidence is None:
            if reason == "blank":
                blank_rows += 1
            elif len(skipped) < 20:
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
                 "skipped": len(skipped), "blank_rows": blank_rows, "linked": linked, "columns": table["header"],
                 "format": table["format"], "sheet": table["sheet"]})
    db.commit()

    hub.publish(ctx.tenant_id, project_id, "evidence.imported",
                {"source_type": source_type, "created": len(created)})

    return {
        "source_type": source_type,
        "created": len(created),
        "duplicates_skipped": duplicates,
        "unusable_rows": len(skipped),
        #: Numbered-but-empty template rows. Counted, not reported as problems.
        "blank_template_rows": blank_rows,
        "linked_to_project_records": linked,
        "detected_columns": table["header"],
        "format": table["format"],
        "sheet": table["sheet"],
        "header_row": table["header_row"],
        # Whatever sat above the header — usually a title carrying the site and date.
        "title_rows": [" ".join(cell for cell in row if cell) for row in table["title_rows"][:2]],
        #: What every record from this file was attributed to.
        "sheet_label": sheet["label"],
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
