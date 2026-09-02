"""A model larger than the import cap has to say so.

Found against a real 97 MB Revit export holding 5,489 elements: the importer stopped at
5,000, dropped 489 without a word, and recorded element_count=5000 as though that were the
whole building. A twin quietly missing part of the structure is worse than one that refuses
the file, because every later answer still looks authoritative.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.services import ifc_service  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = os.path.join(ROOT, "data", "demo_minimal.ifc")


def _synthetic(count: int) -> str:
    body = "\n".join(
        f"#{i + 1}= IFCWALLSTANDARDCASE('guid{i:08d}',#1,'Wall {i}',$,$,#2,#3,$);"
        for i in range(count)
    )
    return f"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC2X3'));\nENDSEC;\nDATA;\n{body}\nENDSEC;\nEND-ISO-10303-21;"


def test_the_cap_still_bounds_the_import_but_the_real_size_is_reported():
    rows, available = ifc_service._fallback_parse(_synthetic(120), limit=50)
    assert len(rows) == 50
    assert available == 120


def test_a_model_under_the_cap_is_not_flagged():
    rows, available = ifc_service._fallback_parse(_synthetic(30), limit=50)
    assert len(rows) == available == 30


def test_parse_ifc_reports_file_size_alongside_the_rows():
    parser, rows, available = ifc_service.parse_ifc(DEMO)
    assert parser in {"ifcopenshell", "step-fallback"}
    assert available >= len(rows) > 0


def test_import_response_admits_an_incomplete_twin(monkeypatch):
    monkeypatch.setattr(ifc_service, "MAX_IMPORT_ELEMENTS", 2)
    with TestClient(app) as client:
        pid = client.post("/api/v1/demo/seed").json()["project_id"]
        with open(DEMO, "rb") as handle:
            response = client.post(
                f"/api/v1/projects/{pid}/bim/import-ifc",
                files={"file": ("demo.ifc", handle, "application/octet-stream")},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["truncated"] is True
        assert body["element_count"] == 2
        assert body["elements_in_file"] > 2
        assert str(body["elements_in_file"]) in body["truncation_notice"]

        models = client.get(f"/api/v1/projects/{pid}/bim/models").json()
        imported = [m for m in models if m["id"] == body["model_document_id"]][0]
        assert imported["meta"]["truncated"] is True
        assert imported["meta"]["elements_in_file"] == body["elements_in_file"]


def test_a_normal_import_is_not_flagged_and_still_reports_a_count():
    with TestClient(app) as client:
        pid = client.post("/api/v1/demo/seed").json()["project_id"]
        with open(DEMO, "rb") as handle:
            body = client.post(
                f"/api/v1/projects/{pid}/bim/import-ifc",
                files={"file": ("demo.ifc", handle, "application/octet-stream")},
            ).json()
    assert body["truncated"] is False
    assert body["truncation_notice"] is None
    assert body["element_count"] == body["elements_in_file"] > 0
