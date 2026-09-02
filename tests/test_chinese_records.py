"""Chinese-language site records.

The retrieval and citation layers were written against Latin text and were silently
blind to anything else: a Chinese tokenizer produced no terms at all, so a project whose
records are kept in Chinese retrieved nothing and every answer came back provisional —
while the citation guard, which is what catches a fabricated source, never fired because
its pattern was ASCII-only.

These tests exist because that combination is worse than a visible failure: the product
looked like it was working.
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

from fastapi.testclient import TestClient

from app.main import app
from app.services.evidence_search import tokenize
from app.services.intelligence import verify_citations

# A punch list in the shape the site actually exports: a title row carrying the station,
# headers on the second row, and numbered items underneath.
PUNCH_LIST = """RS01消项计划表2026/3/11,,,
序号,名称,完成安装时间,备注
1,风管天圆地方、阀门安装,3.22,材料已到货
2,外墙百叶安装及室内排风百叶安装,3.17,
3,配电箱接线以及桥架盖板,3.19,分包队伍未进场
"""

OTHER_STATION = """PL02消项计划表2026/3/10,,,
序号,名称,完成安装时间,备注
1,风管天圆地方、阀门安装,4.05,
2,道路沥青,,材料未到
"""


def headers(tenant: str, organization: str) -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Organization-ID": organization, "X-User-ID": "site", "X-Role": "platform_admin"}


def upload(client: TestClient, project_id: str, head: dict, body: str, name: str = "punch.csv"):
    return client.post(
        f"/api/v1/projects/{project_id}/evidence/import-csv?source_type=punch_list",
        headers=head,
        files={"file": (name, io.BytesIO(body.encode("utf-8")), "text/csv")},
    )


def make_project(client: TestClient, head: dict) -> str:
    return client.post("/api/v1/projects", headers=head, json={"name": "ECRL 二标段", "code": "ECRL-S2"}).json()["id"]


# ------------------------------------------------------------------ tokenizer


def test_chinese_text_produces_search_terms():
    """An ASCII-only tokenizer returned nothing, which disabled retrieval entirely."""
    terms = tokenize("巴西富地站沥青路面分包队伍未进场")
    assert terms, "Chinese text must produce search terms"
    assert "沥青" in terms and "路面" in terms
    # Latin text keeps working unchanged.
    assert tokenize("Crane C02 unavailable") == ["crane", "c02", "unavailable"]
    # Mixed strings yield both kinds of term.
    mixed = tokenize("RS01 环氧地面修补")
    assert "rs01" in mixed and "环氧" in mixed


def test_a_chinese_question_retrieves_chinese_records():
    tenant, organization = "cn-tenant", "cn-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = make_project(client, head)
        assert upload(client, project_id, head, PUNCH_LIST).status_code == 200

        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "风管阀门安装完成了吗？"}
        ).json()
        assert answer["provisional"] is False, "the record is there; retrieval must find it"
        assert any("风管" in item["content"] for item in answer["evidence"])


# ------------------------------------------------------------- record identity


def test_items_are_attributed_to_the_station_named_in_the_sheet_title():
    """Row numbers repeat across stations. Without the sheet's identity, a question about
    one station is answered with another station's work — confidently and wrongly."""
    tenant, organization = "station-tenant", "station-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = make_project(client, head)
        first = upload(client, project_id, head, PUNCH_LIST, "rs01.csv").json()
        second = upload(client, project_id, head, OTHER_STATION, "pl02.csv").json()

        assert first["sheet_label"] == "RS01"
        assert second["sheet_label"] == "PL02"

        rows = client.get(f"/api/v1/projects/{project_id}/evidence", headers=head).json()
        identifiers = {row["source_id"] for row in rows}
        assert "RS01-1" in identifiers and "PL02-1" in identifiers

        # The same item wording at two stations stays two records.
        duct = [row for row in rows if "风管" in row["content"]]
        assert len(duct) == 2
        assert {row["fragment"]["zone"] for row in duct} == {"RS01", "PL02"}


def test_reimporting_the_same_sheet_still_deduplicates():
    with TestClient(app) as client:
        head = headers("cn-dedupe", "cn-dedupe-org")
        project_id = make_project(client, head)
        upload(client, project_id, head, PUNCH_LIST)
        again = upload(client, project_id, head, PUNCH_LIST).json()
        assert again["created"] == 0
        assert again["duplicates_skipped"] == 3


# ------------------------------------------------------------------- citations


def test_citation_checking_works_for_non_latin_identifiers():
    """The guard against fabricated sources must not be language-dependent."""
    result = verify_citations(
        "未完成：IC井盖[巴西富地站-3]、沥青路面[巴西富地站-1]，另见[伪造站-9]。",
        ["巴西富地站-3", "巴西富地站-1", "PL02-1"],
    )
    assert result["verified"] == ["巴西富地站-3", "巴西富地站-1"]
    assert result["unverified"] == ["伪造站-9"]
