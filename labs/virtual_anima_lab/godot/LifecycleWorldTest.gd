extends SceneTree
## E1.2 native contract test; no network, no Core and no agent-world effects.
## godot --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldTest.gd


func _call(world: Node, request_id: int, role: String, op: String, fields: Dictionary = {}) -> Dictionary:
	var request := {
		"protocol": "val.bridge/0.2", "id": request_id,
		"role": role, "op": op,
	}
	for key in fields:
		request[key] = fields[key]
	return world._request(JSON.stringify(request))


func _subjects(observation: Dictionary) -> Array[String]:
	var subjects: Array[String] = []
	for reading in observation["data"]["readings"]:
		subjects.append(reading["subject_ref"])
	return subjects


func _finish(world: Node, ok: bool, reason: String = "") -> void:
	if is_instance_valid(world):
		world.free()
	if ok:
		print("LIFECYCLE_E1_2_NATIVE_PASS")
	else:
		printerr("LIFECYCLE_E1_2_NATIVE_FAIL: " + reason)
	quit(0 if ok else 1)


func _initialize() -> void:
	var world = load("res://LifecycleWorld.gd").new()
	if world == null:
		_finish(world, false, "cannot instantiate lifecycle scene")
		return
	world._seed = 7
	world._reset_world()
	var hello := _call(world, 1, "agent", "hello")
	if not hello["ok"] or hello["data"].has("seed") or hello["data"]["capabilities"] != ["observe"]:
		_finish(world, false, "agent hello revealed harness data or actions")
		return
	var first := _call(world, 2, "agent", "observe")
	if not first["ok"] or first["data"]["schema"] != "anima.lifecycle.world_observation/0.1":
		_finish(world, false, "invalid lifecycle observation")
		return
	var subjects := _subjects(first)
	if not "lab.item.crate" in subjects or not "lab.obstacle.shortcut" in subjects:
		_finish(world, false, "nearby item/blocker not sensed")
		return
	if "lab.zone.delivery" in subjects or "lab.landmark.right" in subjects:
		_finish(world, false, "remote/occluded truth leaked")
		return
	if first["data"]["visibility"] != {"kind": "line_of_sight", "radius": 3}:
		_finish(world, false, "visibility contract")
		return
	if first["data"]["sample_id"] != "worldobs:%s:1:1" % world._world_instance_id:
		_finish(world, false, "sample identity")
		return
	var forbidden := _call(world, 3, "agent", "inspect")
	var forbid_effect := _call(world, 4, "agent", "act", {"direction": "E"})
	var forbid_fixture := _call(world, 5, "agent", "set_obstacle", {
		"at": {"x": 4, "y": 4}, "blocked": true,
	})
	if forbidden["ok"] or forbid_effect["ok"] or forbid_fixture["ok"]:
		_finish(world, false, "agent gained operator truth/effects")
		return
	var full := _call(world, 6, "operator", "inspect")
	if not full["ok"] or full["data"]["shortcut_blocker"] != {"x": 6, "y": 5}:
		_finish(world, false, "harness cannot inspect fixture")
		return
	# Native test deliberately places the observer; this is NOT a bridge operation.
	world._anima = Vector2i(5, 5)
	var behind := _call(world, 7, "agent", "observe")
	if "lab.landmark.right" in _subjects(behind):
		_finish(world, false, "line-of-sight leaked landmark through shortcut blocker")
		return
	world._anima = Vector2i(7, 5)
	var other_side := _call(world, 8, "agent", "observe")
	if not "lab.landmark.right" in _subjects(other_side):
		_finish(world, false, "unobstructed local landmark invisible")
		return
	# Restore actor through a seeded reset, not by exposing a movement API.
	var reset := _call(world, 9, "operator", "reset")
	if not reset["ok"] or reset["epoch"] != 2:
		_finish(world, false, "reset epoch was not updated")
		return
	var before: Dictionary = _call(world, 10, "operator", "inspect")["data"]
	var changed := _call(world, 11, "operator", "set_obstacle", {
		"at": {"x": 4, "y": 4}, "blocked": true,
	})
	if not changed["ok"] or changed["revision"] != 1:
		_finish(world, false, "operator obstacle was not versioned")
		return
	var updated := _call(world, 12, "agent", "observe")
	if not "lab.obstacle.4.4" in _subjects(updated):
		_finish(world, false, "new obstacle not reflected in observation")
		return
	var again := _call(world, 13, "operator", "reset")
	var after: Dictionary = _call(world, 14, "operator", "inspect")["data"]
	if not again["ok"] or after["revision"] != 0:
		_finish(world, false, "reset did not clear revision")
		return
	for field in ["actor", "item", "delivery", "landmark", "shortcut_blocker", "walls", "obstacles"]:
		if before[field] != after[field]:
			_finish(world, false, "seeded reset changed world geometry: " + field)
			return
	var post := _call(world, 15, "agent", "observe")
	if post["data"]["sample_id"] == first["data"]["sample_id"] or post["data"]["epoch"] != 3:
		_finish(world, false, "reset reused sample identity")
		return
	_finish(world, true)
