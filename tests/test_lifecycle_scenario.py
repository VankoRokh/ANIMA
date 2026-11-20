"""E1.2 topology acceptance; checks designer fixture, not ANIMA decision quality."""
import copy
import json

import pytest

from labs.virtual_anima_lab.python.lifecycle.scenarios import (
    load_fixture, reachable, topology,
)


def test_two_independent_crossings_reachable_for_multiple_seeds():
    world = load_fixture()
    upper, middle, lower = world["partition"]["open_y"]
    assert (upper, middle, lower) == (2, 5, 8)
    for seed in (0, 1, 2, 3, 7, 8, 13, 31, 100):
        closed, decoration = topology(seed, world)
        assert tuple(world["shortcut_blocker"]) in closed
        assert (world["partition"]["x"], upper) not in closed
        assert (world["partition"]["x"], lower) not in closed
        assert decoration in closed
        assert reachable(seed, gate_y=upper, data=world)
        assert reachable(seed, gate_y=lower, data=world)
        assert not reachable(seed, gate_y=middle, data=world)


def test_same_seed_same_topology_and_seed_can_change_decoration():
    w = load_fixture()
    assert topology(7, w) == topology(7, w)
    assert topology(7, w)[1] != topology(8, w)[1]


def test_fixture_roles_and_no_planned_route_or_biography():
    w = load_fixture()
    assert w["item"]["ref"] == "lab.item.crate"
    assert w["delivery"]["ref"] == "lab.zone.delivery"
    forbidden = ("route", "solution", "path", "waypoint", "agent_commands", "biography", "goal_reward")
    assert not any(key in w for key in forbidden)


def test_corrupted_scenario_rejected(tmp_path):
    w = load_fixture()
    for key, val in (("actor_start", [True, 5]), ("shortcut_blocker", [0, 1]),
                     ("seeded_obstacles", [[2, 2], [2, 2]]), ("width", True)):
        corrupted = copy.deepcopy(w)
        corrupted[key] = val
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(corrupted), encoding="utf-8")
        with pytest.raises(ValueError):
            load_fixture(path)


def test_seed_validation():
    for value in (-1, True, 2**40, 1.5):
        with pytest.raises(ValueError):
            topology(value)
