from __future__ import annotations
import csv
import io
import re
from datetime import datetime
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.core.security import RequestContext
from app.domain.models import Activity, TwinEntity, MappingRule, GraphRelation, OutboxEvent

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y")

#: P6 and MS Project write logic as "A1010FS+2, A1020SS-1" — an activity id, an optional
#: relationship type and an optional lag.
#:
#: The hyphen is ambiguous: construction activity ids are routinely "P-010" or "A-1010",
#: and a naive lag pattern reads that trailing "-010" as a ten-day negative lag. A lag is
#: therefore only recognised when the schedule marks it as one: after a relationship
#: type, after whitespace, or with an explicit "+". A bare trailing "-N" belongs to the id.
PREDECESSOR_RE = re.compile(
    r"""^\s*
        (?P<activity>[A-Za-z0-9._][A-Za-z0-9._\-]*?)
        # A lag written straight after the id is only a lag when a relationship type
        # says so: "A1010FS-2" is a two-day negative lag, but "P-010" is an activity id.
        (?:\s*(?P<type>FS|SS|FF|SF)\s*(?P<lag_after_type>[+-]\s*\d+(?:\.\d+)?)?)?
        (?:
            \s+(?P<lag_spaced>[+-]?\s*\d+(?:\.\d+)?)   # separated by whitespace
          | (?P<lag_plus>\+\s*\d+(?:\.\d+)?)           # an explicit plus is unambiguous
        )?
        \s*(?:d(?:ays?)?)?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def parse_predecessors(raw: str | None) -> list[dict]:
    """Turn a predecessor cell into structured links."""
    if not raw:
        return []
    links: list[dict] = []
    for chunk in re.split(r"[;,]", str(raw)):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = PREDECESSOR_RE.match(chunk)
        if not match:
            links.append({"activity": chunk, "type": "FS", "lag_days": 0.0, "unparsed": True})
            continue
        lag = (
            match.group("lag_after_type") or match.group("lag_spaced") or match.group("lag_plus") or "0"
        ).replace(" ", "")
        links.append({
            "activity": match.group("activity"),
            "type": (match.group("type") or "FS").upper(),
            "lag_days": float(lag),
        })
    return links

def _dt(v: str | None):
    if not v: return None
    v = v.strip()
    for f in DATE_FORMATS:
        try: return datetime.strptime(v, f)
        except ValueError: pass
    return None

def import_schedule_csv(db: Session, ctx: RequestContext, project_id: str, raw: bytes) -> dict:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    created = []
    for i, row in enumerate(reader):
        ext = row.get("activity_id") or row.get("id") or row.get("Activity ID") or f"CSV-{i+1}"
        name = row.get("name") or row.get("activity_name") or row.get("Activity Name") or ext
        pct = row.get("percent_complete") or row.get("Percent Complete") or "0"
        try: pctf = float(str(pct).replace("%", ""))
        except ValueError: pctf = 0
        a = Activity(
            tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id,
            external_id=str(ext), name=str(name),
            planned_start=_dt(row.get("planned_start") or row.get("Planned Start")),
            planned_finish=_dt(row.get("planned_finish") or row.get("Planned Finish")),
            actual_start=_dt(row.get("actual_start") or row.get("Actual Start")),
            actual_finish=_dt(row.get("actual_finish") or row.get("Actual Finish")),
            percent_complete=pctf,
            total_float_days=float(row.get("total_float_days") or row.get("Total Float") or 0),
            critical=str(row.get("critical") or row.get("Critical") or "").lower() in ("1","true","yes","y"),
            predecessors=parse_predecessors(
                row.get("predecessors") or row.get("Predecessors") or row.get("predecessor") or row.get("depends_on")
            ),
            meta={"source": "csv"},
        )
        db.add(a); created.append(a)
    db.flush()
    with_logic = sum(1 for a in created if a.predecessors)
    db.add(OutboxEvent(topic="schedule.imported", aggregate_type="project", aggregate_id=project_id, payload={"activities": len(created), "format": "csv"}))
    db.commit()
    return {
        "activities_created": len(created),
        "activities_with_logic": with_logic,
        # Said plainly: without logic links the forecast can only resample variance, it
        # cannot trace where a delay travels.
        "logic_note": None if with_logic else "No predecessor column found — critical path analysis will be unavailable.",
        "activity_ids": [a.id for a in created[:100]],
    }

def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 2}

def score(entity: TwinEntity, activity: Activity) -> float:
    a = f"{entity.name} {entity.external_ids.get('ifcType','')} {entity.spatial.get('storey','')} {entity.spatial.get('zone','')}"
    b = f"{activity.external_id} {activity.name}"
    seq = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / max(1, len(ta | tb))
    guid_hit = 1.0 if entity.external_ids.get("ifcGuid") and entity.external_ids.get("ifcGuid") in b else 0.0
    return min(1.0, round(seq * .35 + jac * .55 + guid_hit * .10, 4))

def auto_map(db: Session, ctx: RequestContext, project_id: str, threshold: float = 0.18) -> dict:
    entities = db.query(TwinEntity).filter(TwinEntity.project_id==project_id, TwinEntity.tenant_id==ctx.tenant_id, TwinEntity.organization_id==ctx.organization_id).all()
    acts = db.query(Activity).filter(Activity.project_id==project_id, Activity.tenant_id==ctx.tenant_id, Activity.organization_id==ctx.organization_id).all()
    made = []
    for e in entities:
        candidates = sorted(((score(e,a),a) for a in acts), key=lambda x:x[0], reverse=True)
        if not candidates or candidates[0][0] < threshold: continue
        conf, a = candidates[0]
        exists = db.query(GraphRelation).filter(GraphRelation.project_id==project_id, GraphRelation.source_id==e.id, GraphRelation.relation=="LINKED_TO", GraphRelation.target_id==a.id).first()
        if not exists:
            db.add(GraphRelation(tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id, source_id=e.id, relation="LINKED_TO", target_id=a.id, meta={"strategy":"ai-assisted","confidence":conf}))
        db.add(MappingRule(tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id,
                           source={"entity_id":e.id,"name":e.name}, target={"activity_id":a.id,"external_id":a.external_id,"name":a.name}, strategy="ai-assisted", confidence=conf))
        links = dict(e.links or {}); arr = list(links.get("activities", []));
        if a.id not in arr: arr.append(a.id)
        links["activities"] = arr; e.links = links
        made.append({"entity_id":e.id,"entity_name":e.name,"activity_id":a.id,"activity_name":a.name,"confidence":conf})
    db.add(OutboxEvent(topic="bim.schedule.mapped", aggregate_type="project", aggregate_id=project_id, payload={"mappings":len(made),"threshold":threshold}))
    db.commit()
    return {"mappings_created": len(made), "threshold": threshold, "mappings": made[:500]}
