"""Critical path analysis and delay propagation.

The forecast previously resampled activity variance without asking where a delay
travels. These tests pin the difference: a slip absorbed by a successor's float does not
move the project finish, and one on the critical path does.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

from fastapi.testclient import TestClient

from app.domain.models import Activity
from app.main import app
from app.services.cpm import analyse, propagate_delay
from app.services.mapping_service import parse_predecessors

#: Evaluated at the plan's start, so only activities given an explicit slip count as late.
NOW = datetime(2026, 8, 1)


def activity(external_id, days, predecessors="", slip_days=0.0, critical=False, float_days=0.0):
    """A planned activity, optionally finished late by `slip_days`."""
    start = datetime(2026, 8, 1)
    finish = start + timedelta(days=days)
    return Activity(
        id=f"id-{external_id}",
        external_id=external_id,
        name=f"Activity {external_id}",
        planned_start=start,
        planned_finish=finish,
        actual_finish=finish + timedelta(days=slip_days) if slip_days else None,
        percent_complete=100 if slip_days else 0,
        total_float_days=float_days,
        critical=critical,
        predecessors=parse_predecessors(predecessors),
    )


def test_a_chain_yields_a_critical_path_and_correct_float():
    """A → B → D is the long path; C hangs off A with slack."""
    network = analyse([
        activity("A", 5),
        activity("B", 10, "A"),
        activity("C", 2, "A"),
        activity("D", 4, "B; C"),
    ], now=NOW)

    assert network["available"] is True
    assert network["method"] == "cpm-forward-backward-pass"
    assert network["project_duration_days"] == 19  # 5 + 10 + 4
    path = [step["activity"] for step in network["critical_path"]]
    assert path == ["A", "B", "D"]
    # C is off the critical path by exactly the difference between the two branches.
    assert network["float_distribution"]["zero"] == 3
    assert network["float_distribution"]["over_5_days"] == 1


def test_a_lag_extends_the_path():
    with_lag = analyse([activity("A", 5), activity("B", 5, "AFS+3")], now=NOW)
    without = analyse([activity("A", 5), activity("B", 5, "A")], now=NOW)
    assert with_lag["project_duration_days"] - without["project_duration_days"] == 3


def test_a_schedule_without_logic_says_so_instead_of_inventing_a_path():
    network = analyse([activity("A", 5), activity("B", 10)], now=NOW)
    assert network["available"] is False
    assert "predecessor" in network["reason"].lower()
    # Every activity being independent must not be presented as "everything is critical".
    assert "critical_path" not in network


def test_a_circular_dependency_is_reported_not_looped_over():
    network = analyse([activity("A", 3, "B"), activity("B", 3, "A")], now=NOW)
    assert network["available"] is False
    assert "cycle" in network["reason"].lower()


def test_a_missing_predecessor_is_warned_about_and_the_rest_still_computes():
    """An id that looks like a lag ("GHOST-1") must stay an id."""
    network = analyse([activity("A", 5), activity("B", 5, "A; GHOST-1")], now=NOW)
    assert network["available"] is True
    assert any("GHOST-1" in warning for warning in network["warnings"])
    assert network["project_duration_days"] == 10


def test_slip_absorbed_by_float_does_not_move_the_project_finish():
    """The distinction the old forecast could not make."""
    result = propagate_delay([
        activity("A", 5),
        activity("B", 10, "A"),
        activity("C", 2, "A", slip_days=3),   # 8 days of float, slips 3
        activity("D", 4, "B; C"),
    ], now=NOW)

    propagation = result["delay_propagation"]
    assert propagation["total_measured_slip_days"] == 3
    assert propagation["project_impact_days"] == 0, "a slip inside float must not move the finish"
    assert propagation["absorbed_by_float_days"] == 3


def test_slip_on_the_critical_path_moves_the_project_finish():
    result = propagate_delay([
        activity("A", 5),
        activity("B", 10, "A", slip_days=4),  # zero float
        activity("C", 2, "A"),
        activity("D", 4, "B; C"),
    ], now=NOW)

    propagation = result["delay_propagation"]
    assert propagation["project_impact_days"] == 4
    assert propagation["absorbed_by_float_days"] == 0
    contributor = propagation["contributors"][0]
    assert contributor["activity"] == "B"
    # The whole four-day impact is attributable to B.
    assert contributor["project_impact_contribution_days"] == 4


def test_the_network_reports_where_it_disagrees_with_the_imported_plan():
    """Neither source is assumed right; the disagreement is the finding."""
    network = analyse([
        activity("A", 5, critical=False),          # computed critical, plan says no
        activity("B", 10, "A", critical=True),
        activity("D", 4, "B", critical=True),
    ], now=NOW)
    disagreements = {row["activity"] for row in network["disagreements_with_source"]}
    assert "A" in disagreements


# --------------------------------------------------------------- through the API


def headers(tenant, organization):
    return {"X-Tenant-ID": tenant, "X-Organization-ID": organization, "X-User-ID": "planner", "X-Role": "platform_admin"}


SCHEDULE_WITH_LOGIC = """activity_id,name,planned_start,planned_finish,percent_complete,predecessors
P-010,Piling,2026-08-01,2026-08-06,100,
P-020,Pile caps,2026-08-06,2026-08-16,100,P-010
P-030,Site fencing,2026-08-06,2026-08-08,100,P-010
P-040,Ground slab,2026-08-16,2026-08-20,0,P-020; P-030
"""


def test_a_schedule_import_carries_its_logic_into_the_forecast():
    with TestClient(app) as client:
        head = headers("cpm-tenant", "cpm-org")
        project_id = client.post("/api/v1/demo/seed", headers=head).json()["project_id"]

        imported = client.post(
            f"/api/v1/projects/{project_id}/schedules/import-csv",
            headers=head,
            files={"file": ("p6.csv", io.BytesIO(SCHEDULE_WITH_LOGIC.encode()), "text/csv")},
        ).json()
        assert imported["activities_with_logic"] == 3
        assert imported["logic_note"] is None

        forecast = client.post(f"/api/v1/projects/{project_id}/forecast", headers=head).json()
        critical = forecast["critical_path"]
        assert critical["available"] is True
        assert critical["method"] == "cpm-forward-backward-pass"
        assert [step["activity"] for step in critical["path"]][:3] == ["P-010", "P-020", "P-040"]
        assert "absorbed by float" in forecast["interpretation"]


def test_a_schedule_without_logic_tells_the_planner_what_is_missing():
    with TestClient(app) as client:
        head = headers("nologic-tenant", "nologic-org")
        project_id = client.post("/api/v1/demo/seed", headers=head).json()["project_id"]
        forecast = client.post(f"/api/v1/projects/{project_id}/forecast", headers=head).json()
        assert forecast["critical_path"]["available"] is False
        assert "predecessor" in forecast["critical_path"]["reason"].lower()
        assert "Import a predecessor column" in forecast["interpretation"]


def test_activity_ids_containing_hyphens_are_not_read_as_lag():
    """Construction ids are routinely "P-010"; a naive lag pattern turns that into -10 days."""
    assert parse_predecessors("P-010") == [{"activity": "P-010", "type": "FS", "lag_days": 0.0}]
    assert parse_predecessors("A-1010FS-2") == [{"activity": "A-1010", "type": "FS", "lag_days": -2.0}]
    assert parse_predecessors("A1010+3")[0]["lag_days"] == 3.0


def test_a_chain_of_floated_activities_does_not_absorb_the_same_slack_twice():
    """Total float is shared along a path; free float is not.

    B and C each show 5 days of total float, but that is the *same* five days. Using
    total float to absorb delay at every node would silently swallow ten.
    """
    # A→B→C→END is 15 days of work; A→LONG→END is 20. The B/C branch therefore holds
    # exactly five days of slack between the two of them.
    result = propagate_delay([
        activity("A", 5),
        activity("B", 5, "A", slip_days=4),
        activity("C", 5, "B", slip_days=4),
        activity("LONG", 15, "A"),
        activity("END", 1, "C; LONG"),
    ], now=NOW)

    nodes = {row["activity"]: row for row in result["delay_propagation"]["contributors"]}
    assert nodes["B"]["free_float_days"] == 0, "B's successor starts immediately after it"
    assert nodes["C"]["free_float_days"] == 5, "the slack sits where the branch merges"

    propagation = result["delay_propagation"]
    assert propagation["total_measured_slip_days"] == 8
    assert propagation["project_impact_days"] == 3
    assert propagation["absorbed_by_float_days"] == 5


def test_an_activity_whose_delay_a_successor_absorbs_contributes_nothing():
    """"Did this actually cost us time?" is the question a planner asks."""
    result = propagate_delay([
        activity("A", 5),
        activity("B", 5, "A", slip_days=2),   # passes its slip to C
        activity("C", 5, "B"),                # holds the slack that swallows it
        activity("LONG", 15, "A"),
        activity("END", 1, "C; LONG"),
    ], now=NOW)
    propagation = result["delay_propagation"]
    assert propagation["project_impact_days"] == 0
    assert propagation["contributors"][0]["activity"] == "B"
    assert propagation["contributors"][0]["project_impact_contribution_days"] == 0


def test_unlinked_activities_are_excluded_from_the_disagreement_report():
    """A schedule with partial logic must not accuse the plan over its unlinked rows."""
    network = analyse([
        activity("A", 5),
        activity("B", 10, "A", critical=True),
        activity("ORPHAN", 2, critical=True),  # no links at all
    ], now=NOW)
    reported = {row["activity"] for row in network["disagreements_with_source"]}
    assert "ORPHAN" not in reported
    assert network["activities_without_logic"] == 1
    assert "ORPHAN" in network["unlinked_examples"]
