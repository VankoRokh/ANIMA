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
    assert choice.basis in ("memory_hypothesis", "current_uncertainty")


def test_state_schema_is_versioned():
    assert CONTROL_SCHEMA == "anima.lab.visual_runner_state/0.1"
