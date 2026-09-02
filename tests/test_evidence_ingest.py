"""Evidence ingestion — the four site sources the pilot scenario declares.

The twin's answers are bounded by what it can retrieve, so these tests are about
whether a real site export becomes *retrievable, attributable* evidence: deduplicated
across re-imports, linked to the activity or element it refers to, and weighted by how
dependable its source is.
"""
from __future__ import annotations

import io
import os
import struct
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

import pytest
from fastapi.testclient import TestClient

from app.main import app


def headers(tenant: str, organization: str, role: str = "platform_admin") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Organization-ID": organization, "X-User-ID": "importer", "X-Role": role}


def seed(client: TestClient, tenant: str, organization: str) -> str:
    return client.post("/api/v1/demo/seed", headers=headers(tenant, organization)).json()["project_id"]


DAILY_REPORTS = """date,report_no,author,description,activity_id,zone
2026-08-21,DR-301,Site Engineer,"Concrete pour for Zone C slab completed; 42 m3 placed.",A1028,Zone C
2026-08-22,DR-302,Site Engineer,"Tower crane TC-01 out of service from 09:00 awaiting spare part; steel erection halted.",A1024,Roof Zone C
2026-08-23,DR-303,Foreman,"Steel erection resumed at 13:20 after crane repair.",A1024,Roof Zone C
"""

NCR_ROWS = """id,title,description,status,raised_by,date,ifc_guid
NCR-201,Weld porosity on splice plate,"Porosity found on the splice plate weld at gridline C4; grinding and re-weld required.",open,QA Inspector,2026-08-22,3lXDemoB023
NCR-202,Missing shim,"Shim missing under base plate; corrected on site.",closed,QA Inspector,2026-08-20,
"""


RFI_ROWS = """rfi_no,subject,description,status,date
RFI-088,Anchor bolt spacing clarification,"Drawing S-204 shows 180mm spacing; site condition allows 200mm. Confirm acceptable.",open,2026-08-21
"""


def upload_csv(client: TestClient, project_id: str, head: dict, source_type: str, body: str):
    return client.post(
        f"/api/v1/projects/{project_id}/evidence/import-csv?source_type={source_type}",
        headers=head,
        files={"file": ("export.csv", io.BytesIO(body.encode()), "text/csv")},
    )


# ----------------------------------------------------------------- csv import


def test_daily_reports_become_retrievable_evidence_linked_to_their_activity():
    tenant, organization = "ingest-tenant", "ingest-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        result = upload_csv(client, project_id, head, "daily_report", DAILY_REPORTS)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["created"] == 3
        assert body["duplicates_skipped"] == 0
        # The seeded schedule contains A1024 and A1028, so those rows resolve to real ids.
        assert body["linked_to_project_records"] >= 2

        listed = client.get(f"/api/v1/projects/{project_id}/evidence?source_type=daily_report", headers=head).json()
        crane = next(row for row in listed if "TC-01" in row["content"])
        assert crane["source_id"] == "DR-302"
        assert crane["confidence"] == 0.88  # narrative, not a signed record
        links = crane["fragment"]["links"]
        assert links["activity_ref"] == "A1024"
        assert links["activity_id"], "an activity that exists must be resolved to its id"
        assert crane["fragment"]["zone"] == "Roof Zone C"
        assert crane["fragment"]["recorded_at"].startswith("2026-08-22")


def test_reimporting_the_same_export_creates_nothing_new():
    """Site systems re-send constantly; an importer that duplicates is unusable."""
    tenant, organization = "dedupe-tenant", "dedupe-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        first = upload_csv(client, project_id, head, "daily_report", DAILY_REPORTS).json()
        second = upload_csv(client, project_id, head, "daily_report", DAILY_REPORTS).json()

        assert first["created"] == 3
        assert second["created"] == 0
        assert second["duplicates_skipped"] == 3

        # The seed already contains two daily reports, so count the imported ones.
        listed = client.get(f"/api/v1/projects/{project_id}/evidence?source_type=daily_report", headers=head).json()
        imported = [row for row in listed if row["source_id"].startswith("DR-30")]
        assert len(imported) == 3


def test_formal_records_carry_higher_confidence_than_narratives():
    tenant, organization = "confidence-tenant", "confidence-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)
        upload_csv(client, project_id, head, "ncr", NCR_ROWS)
        upload_csv(client, project_id, head, "daily_report", DAILY_REPORTS)

        rows = client.get(f"/api/v1/projects/{project_id}/evidence", headers=head).json()
        ncr = next(row for row in rows if row["source_id"] == "NCR-201")
        report = next(row for row in rows if row["source_id"] == "DR-301")
        assert ncr["confidence"] > report["confidence"]
        # Status is folded into the indexed text: "is the NCR closed" is a real question.
        assert "Status: open" in ncr["content"]
        # An element GUID that exists in the twin resolves to the element.
        assert ncr["fragment"]["links"].get("entity_id"), "a known IFC GUID must resolve"


def test_an_unusable_row_is_reported_rather_than_silently_dropped():
    with TestClient(app) as client:
        head = headers("bad-row-tenant", "bad-row-org")
        project_id = seed(client, "bad-row-tenant", "bad-row-org")
        result = upload_csv(client, project_id, head, "note", "id,author\nX-1,someone\nX-2,someone else\n").json()
        assert result["created"] == 0
        assert result["unusable_rows"] == 2
        # The message says what was looked for, so the uploader can fix the file.
        assert "no usable description" in result["problems"][0]
        assert "description" in result["problems"][0]


def test_numbered_but_empty_template_rows_are_not_reported_as_failures():
    """Site templates ship with blank numbered rows; counting them as errors makes a
    clean import look broken."""
    with TestClient(app) as client:
        head = headers("blank-tenant", "blank-org")
        project_id = seed(client, "blank-tenant", "blank-org")
        body = "序号,名称\n1,围栏安装\n2,沥青路面\n3,\n4,\n5,\n"
        result = upload_csv(client, project_id, head, "punch_list", body).json()
        assert result["created"] == 2
        assert result["blank_template_rows"] == 3
        assert result["unusable_rows"] == 0
        assert result["problems"] == []


def test_an_unrecognised_item_column_is_inferred_and_disclosed():
    """No alias list survives real site templates: one calls it 名称, the next
    剩余主要工作内容."""
    with TestClient(app) as client:
        head = headers("infer-tenant", "infer-org")
        project_id = seed(client, "infer-tenant", "infer-org")
        body = "序号,剩余主要工作内容,计划完成时间\n1,围栏安装,4.11\n"
        result = upload_csv(client, project_id, head, "punch_list", body).json()
        assert result["created"] == 1

        rows = client.get(f"/api/v1/projects/{project_id}/evidence?source_type=punch_list", headers=head).json()
        assert "围栏安装" in rows[0]["content"]
        # Which column was guessed is recorded, so the choice can be checked.
        assert rows[0]["fragment"]["content_column_inferred"] == "剩余主要工作内容"


def test_an_unknown_source_type_names_the_supported_ones():
    with TestClient(app) as client:
        head = headers("type-tenant", "type-org")
        project_id = seed(client, "type-tenant", "type-org")
        response = upload_csv(client, project_id, head, "gossip", DAILY_REPORTS)
        assert response.status_code == 400
        assert "daily_report" in response.json()["detail"]


def test_importing_evidence_requires_write_permission_and_stays_in_tenant():
    with TestClient(app) as client:
        project_id = seed(client, "scope-tenant", "scope-org")
        viewer = headers("scope-tenant", "scope-org", "viewer")
        assert upload_csv(client, project_id, viewer, "daily_report", DAILY_REPORTS).status_code == 403
        outsider = headers("other-tenant", "other-org")
        assert upload_csv(client, project_id, outsider, "daily_report", DAILY_REPORTS).status_code == 404


# --------------------------------------------------------------------- photos


def _jpeg_with_exif(taken: str = "2026:08:14 07:42:11") -> bytes:
    """A minimal but genuine JPEG carrying DateTimeOriginal and a GPS position."""
    E = ">"

    def rational(numerator: int, denominator: int = 1) -> bytes:
        return struct.pack(E + "II", numerator, denominator)

    def build(entries, offset, next_ifd=0):
        data_start = offset + 2 + 12 * len(entries) + 4
        head = struct.pack(E + "H", len(entries))
        blob = b""
        for tag, ftype, count, payload in entries:
            if len(payload) <= 4:
                value = payload + b"\x00" * (4 - len(payload))
            else:
                value = struct.pack(E + "I", data_start + len(blob))
                blob += payload
            head += struct.pack(E + "HHI", tag, ftype, count) + value
        head += struct.pack(E + "I", next_ifd)
        return head + blob

    root_entries = [
        (0x0132, 2, 20, b"2026:08:20 09:00:00\x00"),
        (0x8769, 4, 1, struct.pack(E + "I", 0)),
        (0x8825, 4, 1, struct.pack(E + "I", 0)),
    ]
    root_size = len(build(root_entries, 8))
    exif_off = 8 + root_size
    exif_ifd = build([(0x9003, 2, 20, f"{taken}\x00".encode())], exif_off)
    gps_off = exif_off + len(exif_ifd)
    gps_ifd = build([
        (0x0001, 2, 2, b"N\x00"),
        (0x0002, 5, 3, rational(22) + rational(32) + rational(3336, 100)),
        (0x0003, 2, 2, b"E\x00"),
        (0x0004, 5, 3, rational(114) + rational(3) + rational(3456, 100)),
    ], gps_off)
    root_ifd = build([
        (0x0132, 2, 20, b"2026:08:20 09:00:00\x00"),
        (0x8769, 4, 1, struct.pack(E + "I", exif_off)),
        (0x8825, 4, 1, struct.pack(E + "I", gps_off)),
    ], 8)

    payload = b"Exif\x00\x00" + b"MM\x00\x2a" + struct.pack(E + "I", 8) + root_ifd + exif_ifd + gps_ifd
    return b"\xff\xd8\xff\xe1" + struct.pack(E + "H", len(payload) + 2) + payload + b"\xff\xd9"


def test_a_photo_is_dated_by_its_own_metadata_not_by_upload_time():
    """A photo reaching the office days later is evidence about the day it was taken."""
    tenant, organization = "photo-tenant", "photo-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        response = client.post(
            f"/api/v1/projects/{project_id}/evidence/photos",
            headers=head,
            files={"file": ("site.jpg", io.BytesIO(_jpeg_with_exif()), "image/jpeg")},
            data={"caption": "Splice plate weld at gridline C4 before rework", "activity_id": "A1024"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created"] is True
        assert body["exif_found"] is True
        assert body["taken_at"].startswith("2026-08-14T07:42:11")
        assert body["linked"]["activity_ref"] == "A1024"

        rows = client.get(f"/api/v1/projects/{project_id}/evidence?source_type=photo", headers=head).json()
        photo = rows[0]
        assert photo["fragment"]["taken_at_source"] == "exif"
        assert photo["fragment"]["gps"] == {"latitude": 22.5426, "longitude": 114.0596}
        # The caption is what retrieval can actually match on.
        assert "splice plate" in photo["content"].lower()

        image = client.get(f"/api/v1/projects/{project_id}/evidence/{photo['id']}/image", headers=head)
        assert image.status_code == 200
        assert image.content[:2] == b"\xff\xd8"

        # The image is tenant-scoped like every other stored asset.
        outsider = client.get(
            f"/api/v1/projects/{project_id}/evidence/{photo['id']}/image",
            headers=headers("photo-outsider", "photo-outsider-org"),
        )
        assert outsider.status_code == 404


def test_the_same_photograph_uploaded_twice_is_stored_once():
    with TestClient(app) as client:
        head = headers("photo-dup-tenant", "photo-dup-org")
        project_id = seed(client, "photo-dup-tenant", "photo-dup-org")
        image = _jpeg_with_exif()
        payload = {"caption": "Same shot"}
        first = client.post(f"/api/v1/projects/{project_id}/evidence/photos", headers=head,
                            files={"file": ("a.jpg", io.BytesIO(image), "image/jpeg")}, data=payload).json()
        second = client.post(f"/api/v1/projects/{project_id}/evidence/photos", headers=head,
                             files={"file": ("b.jpg", io.BytesIO(image), "image/jpeg")}, data=payload).json()
        assert first["created"] is True
        assert second["created"] is False and second["duplicate"] is True
        assert second["evidence_id"] == first["evidence_id"]


def test_a_non_image_upload_is_refused_with_the_accepted_types():
    with TestClient(app) as client:
        head = headers("photo-type-tenant", "photo-type-org")
        project_id = seed(client, "photo-type-tenant", "photo-type-org")
        response = client.post(
            f"/api/v1/projects/{project_id}/evidence/photos",
            headers=head,
            files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert response.status_code == 400
        assert ".jpg" in response.json()["detail"]


# ------------------------------------------------------------------- coverage


def test_coverage_names_the_sources_that_are_still_missing():
    """The honest answer to "can this twin reason yet"."""
    tenant, organization = "coverage-tenant", "coverage-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        before = client.get(f"/api/v1/projects/{project_id}/evidence/coverage", headers=head).json()
        assert "inspection" in before["sources_present"]  # the seed includes one
        assert "photo" in before["sources_missing"]

        # The seed already covers daily_report, ncr and inspection, so importing an RFI
        # is what actually widens coverage.
        upload_csv(client, project_id, head, "rfi", RFI_ROWS)
        after = client.get(f"/api/v1/projects/{project_id}/evidence/coverage", headers=head).json()
        assert after["total"] > before["total"]
        assert "rfi" in after["sources_present"]
        assert after["coverage_ratio"] > before["coverage_ratio"]


# ------------------------------------------------------- effect on the product


def test_imported_evidence_is_actually_retrieved_by_ask_twin():
    """Ingestion only matters if it changes what the twin can answer.

    The question is chosen so that no seeded record touches it: the seed is about crane
    downtime, weld quality and decking, and says nothing about a concrete pour.
    """
    tenant, organization = "retrieval-tenant", "retrieval-org"
    question = {"question": "Was the concrete pour for the Zone C slab completed?"}
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        before = client.post(f"/api/v1/projects/{project_id}/ask", headers=head, json=question).json()
        assert before["provisional"] is True, "no seeded record mentions a concrete pour"

        upload_csv(client, project_id, head, "daily_report", DAILY_REPORTS)

        after = client.post(f"/api/v1/projects/{project_id}/ask", headers=head, json=question).json()
        assert after["provisional"] is False
        assert any(item["source_id"] == "DR-301" for item in after["evidence"])


def test_a_coincidental_match_on_a_common_word_is_not_evidence():
    """The failure this guards against turns "no record" into a confident answer.

    Nearly every site record mentions a "zone". Before this rule, a question about a
    concrete pour retrieved three unrelated records on that single word and the answer
    came back as evidence-backed.
    """
    tenant, organization = "coincidence-tenant", "coincidence-org"
    with TestClient(app) as client:
        head = headers(tenant, organization)
        project_id = seed(client, tenant, organization)

        answer = client.post(
            f"/api/v1/projects/{project_id}/ask",
            headers=head,
            json={"question": "Was the concrete pour for the Zone C slab completed?"},
        ).json()
        assert answer["evidence"] == []
        assert answer["provisional"] is True

        # A question whose distinctive terms really are in the corpus still lands.
        grounded = client.post(
            f"/api/v1/projects/{project_id}/ask",
            headers=head,
            json={"question": "What was the weld quality issue in Zone B?"},
        ).json()
        assert grounded["provisional"] is False
        assert any(item["source_id"] == "NCR-118" for item in grounded["evidence"])


# ------------------------------------------------------------------- geometry


def test_proxy_geometry_says_which_kind_of_problem_it_is():
    """"Install IfcOpenShell" is wrong advice when it is already installed.

    A proxy mesh has two very different causes: the deployment cannot triangulate, or
    the element simply carries no geometry. Only the first is something an operator can
    fix, and the message must not send them after the wrong one. The assertions hold
    whether or not the environment running them has IfcOpenShell.
    """
    import os

    with TestClient(app) as client:
        head = headers("geometry-tenant", "geometry-org")
        project_id = seed(client, "geometry-tenant", "geometry-org")
        ifc_path = os.path.join(os.path.dirname(__file__), "..", "data", "demo_minimal.ifc")
        with open(ifc_path, "rb") as handle:
            document_id = client.post(
                f"/api/v1/projects/{project_id}/bim/import-ifc",
                headers=head,
                files={"file": ("demo.ifc", handle, "application/octet-stream")},
            ).json()["model_document_id"]

        geometry = client.get(
            f"/api/v1/projects/{project_id}/bim/models/{document_id}/geometry", headers=head
        ).json()

        assert "triangulation_available" in geometry
        # Spatial containers are counted separately: a site node without a mesh is not a
        # gap in the model.
        assert geometry["spatial_proxies"] >= 1
        assert geometry["exact_meshes"] + geometry["proxy_meshes"] == geometry["mesh_count"]

        disclaimer = geometry["disclaimer"] or ""
        if not geometry["triangulation_available"]:
            assert "INSTALL_IFC" in disclaimer, "an operator must be told what to change"
        elif geometry["element_proxies"]:
            assert "property of the model" in disclaimer
            assert "Install IfcOpenShell" not in disclaimer
        else:
            assert geometry["geometry_mode"] == "ifc-exact"
