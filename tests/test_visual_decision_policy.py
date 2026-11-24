"""Deterministic visual decision policy: no hidden world truth, no FAST."""
from __future__ import annotations

from labs.virtual_anima_lab.python.lifecycle.visual_runner import (
    CrateInvestigationPolicy, PolicyChoice, CONTROL_SCHEMA,
)


def view(bearing=None, distance=1000):
    rows = [] if bearing is None else [{
        "entity_ref": "lab.item.crate", "category": "item",
        "bearing_mdeg": bearing, "range_milli_cells": distance,
        "properties": {"owner": {"status": "absent", "value": None}},
    }]
    return {"readings": rows}


def pose(heading=0, *, current_sample="second"):
    return {"poses": [
        {"sample_id": "first", "relative_heading_quadrants": 1,
         "local_right_steps": 0, "local_forward_steps": 0},
        {"sample_id": current_sample, "relative_heading_quadrants": heading,
         "local_right_steps": 0, "local_forward_steps": 0},
    ]}


def memory(enabled=False, *, remembered=False):
    result = {"memory_enabled": enabled, "entities": []}
    if remembered:
        result["entities"] = [{
            "entity_ref": "lab.item.crate", "last_seen_sample": "first",
            "last_seen_view": {"bearing_mdeg": 0, "range_milli_cells": 1000},
        }]
    return result


def test_unobserved_unremembered_starts_search():
    assert CrateInvestigationPolicy.propose(
        view(), memory(), pose()
    ) == PolicyChoice("world.turn", "right", "SEARCH_NEW_VIEW", "current_uncertainty")


def test_direct_sensor_reorients_and_proposes_approach():
    p = CrateInvestigationPolicy
    assert p.propose(view(25_000), memory(), pose()).direction == "right"
    assert p.propose(view(-25_000), memory(), pose()).direction == "left"
    near = p.propose(view(0, 1000), memory(), pose())
    assert near.kind == "world.step" and near.approach_finishes
    far = p.propose(view(0, 4000), memory(), pose())
    assert far.kind == "world.step" and not far.approach_finishes
    assert near.basis == "current_raw"


def test_bounded_memory_hypothesis_changes_search_direction():
    recalled = memory(enabled=True, remembered=True)
    choice = CrateInvestigationPolicy.propose(view(), recalled, pose(0))
    assert choice.kind == "world.turn" and choice.direction == "right"
    assert choice.reason == "CHECK_REMEMBERED_TARGET"
    choice_without_history = CrateInvestigationPolicy.propose(
        view(), memory(False, remembered=True), pose(0)
    )
    assert choice_without_history.reason == "SEARCH_NEW_VIEW"


def test_memory_geometry_does_not_authorize_blind_step():
    recalled = memory(enabled=True, remembered=True)
    choice = CrateInvestigationPolicy.propose(view(), recalled, pose(1))
    assert choice.kind == "world.turn"
    assert choice.basis in ("memory_hypothesis", "current_uncertainty", "suspected_stale_hypothesis")


def test_state_schema_is_versioned():
    assert CONTROL_SCHEMA == "anima.lab.visual_runner_state/0.1"


def test_familiar_crate_changes_first_decision_only_with_memory():
    recalled = memory(enabled=True, remembered=True)
    first = CrateInvestigationPolicy.propose(view(), recalled, pose(2))
    no_history = CrateInvestigationPolicy.propose(
        view(), memory(), pose(2),
    )
    assert first.reason == "CHECK_REMEMBERED_TARGET"
    assert first.direction == "left" and first.basis == "memory_hypothesis"
    assert no_history.reason == "SEARCH_NEW_VIEW"
    assert no_history.direction == "right"


def test_missing_crate_at_predicted_visible_position_weakens_hypothesis():
    recalled = memory(enabled=True, remembered=True)
    choice = CrateInvestigationPolicy.propose(view(), recalled, pose(1))
    assert choice.kind == "world.turn"
    assert choice.reason == "PRIOR_LOCATION_NOT_REOBSERVED"
    assert choice.suspect_prior_sample == "first"
    assert choice.basis == "suspected_stale_hypothesis"
    afterwards = CrateInvestigationPolicy.propose(
        view(), recalled, pose(1), stale_sample_ids=frozenset(("first",)),
    )
    assert afterwards.reason == "SEARCH_AFTER_MEMORY_CONFLICT"
    assert afterwards.suspect_prior_sample is None


def test_possible_occlusion_prevents_false_memory_contradiction():
    recalled = memory(enabled=True, remembered=True)
    occluded = view()
    occluded["readings"] = [{
        "entity_ref": "lab.obstacle.opaque",
        "category": "obstacle",
        "bearing_mdeg": 0,
        "range_milli_cells": 300,
        "properties": {},
    }]
    choice = CrateInvestigationPolicy.propose(occluded, recalled, pose(1))
    assert choice.suspect_prior_sample is None
    assert choice.reason != "PRIOR_LOCATION_NOT_REOBSERVED"


def test_direct_current_evidence_overrides_prior_stale_hypothesis():
    recalled = memory(enabled=True, remembered=True)
    choice = CrateInvestigationPolicy.propose(
        view(0), recalled, pose(3), stale_sample_ids=frozenset(("first",)),
    )
    assert choice.kind == "world.step" and choice.basis == "current_raw"
