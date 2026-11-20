"""E1.2 fixture verification for the isolated Godot scene; NOT an agent planner.

This module reads designer truth only for tests. It must never be imported into
the agent's Context, FAST-stub, or a runtime action selector.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "godot" / "LifecycleScenario.json"


def _cell(raw: object, width: int, height: int) -> tuple[int, int]:
    if (
        type(raw) is not list or len(raw) != 2
        or any(type(v) is not int for v in raw)
        or not 0 <= raw[0] < width or not 0 <= raw[1] < height
    ):
        raise ValueError("invalid fixture cell")
    return raw[0], raw[1]


def load_fixture(path: Path = FIXTURE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema", "world_version", "width", "height", "actor_start",
                "item", "delivery", "partition", "shortcut_blocker", "landmark",
                "seeded_obstacles", "sensor"}
    if type(data) is not dict or set(data) != required:
        raise ValueError("invalid scenario fields")
    if data["schema"] != "anima.lifecycle.world_scenario/0.1" or data["world_version"] != "lifecycle-grid/0.1":
        raise ValueError("invalid scenario version")
    width, height = data["width"], data["height"]
    if type(width) is not int or type(height) is not int or not (9 <= width <= 30 and 9 <= height <= 30):
        raise ValueError("unsupported fixture dimensions")
    if data["sensor"] != {"kind": "line_of_sight", "radius": 3}:
        raise ValueError("unsupported sensor fixture")
    for field in ("actor_start", "shortcut_blocker"):
        _cell(data[field], width, height)
    for key in ("item", "delivery", "landmark"):
        item = data[key]
        if type(item) is not dict or set(item) != {"ref", "at"} or type(item["ref"]) is not str or not item["ref"].startswith("lab."):
            raise ValueError(f"invalid {key} fixture")
        _cell(item["at"], width, height)
    part = data["partition"]
    if type(part) is not dict or set(part) != {"x", "open_y"} or type(part["x"]) is not int or not 1 < part["x"] < width - 2:
        raise ValueError("invalid partition")
    if type(part["open_y"]) is not list or len(part["open_y"]) != 3 or any(type(y) is not int for y in part["open_y"]):
        raise ValueError("invalid wall gates")
    if not (1 < part["open_y"][0] < part["open_y"][1] < part["open_y"][2] < height - 2):
        raise ValueError("invalid wall gate order")
    if _cell(data["shortcut_blocker"], width, height) != (part["x"], part["open_y"][1]):
        raise ValueError("shortcut must be physically blocked")
    choices = data["seeded_obstacles"]
    if type(choices) is not list or not choices or len(choices) > 16:
        raise ValueError("invalid decoration choices")
    cells = [_cell(entry, width, height) for entry in choices]
    if len(cells) != len(set(cells)):
        raise ValueError("duplicate decoration")
    return data


def topology(seed: int, data: dict | None = None) -> tuple[set[tuple[int, int]], tuple[int, int]]:
    """Test-only topology; no route or full map is passed to ANIMA."""
    if type(seed) is not int or seed < 0 or seed > 2_147_483_647:
        raise ValueError("invalid seed")
    data = data or load_fixture()
    width, height = data["width"], data["height"]
    closed = {(x, 0) for x in range(width)}
    closed |= {(x, height - 1) for x in range(width)}
    closed |= {(0, y) for y in range(height)}
    closed |= {(width - 1, y) for y in range(height)}
    px, gates = data["partition"]["x"], data["partition"]["open_y"]
    closed |= {(px, y) for y in range(1, height - 1) if y not in gates}
    closed.add(tuple(data["shortcut_blocker"]))
    decoration = tuple(data["seeded_obstacles"][seed % len(data["seeded_obstacles"])])
    if decoration in closed:
        raise ValueError("seeded obstacle overlaps fixed blocker")
    closed.add(decoration)
    for target in (data["actor_start"], data["item"]["at"], data["delivery"]["at"], data["landmark"]["at"]):
        if tuple(target) in closed:
            raise ValueError("fixture object overlaps blocked cell")
    return closed, decoration


def reachable(seed: int, *, gate_y: int, data: dict | None = None) -> bool:
    """Acceptance oracle only: force one designated crossing, not agent policy."""
    data = data or load_fixture()
    walls, _ = topology(seed, data)
    px = data["partition"]["x"]
    start = tuple(data["actor_start"])
    goal = tuple(data["delivery"]["at"])
    todo = deque([start])
    seen = {start}
    while todo:
        x, y = todo.popleft()
        if (x, y) == goal:
            return True
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            cell = (x + dx, y + dy)
            if cell in walls or cell in seen:
                continue
            if cell[0] == px and cell[1] != gate_y:
                continue
            seen.add(cell)
            todo.append(cell)
    return False
