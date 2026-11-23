extends SceneTree
## E1.3 native Godot contract: opt-in world effects, no Core or model authority.
## run: godot --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldActionTest.gd

func _call(world: Node, request_id: int, role: String, op: String, extra: Dictionary = {}) -> Dictionary:
	var req := {"protocol": "val.bridge/0.2", "id": request_id, "role": role, "op": op}
	for key in extra:
		req[key] = extra[key]
	return world._request(JSON.stringify(req))


func _action(obs: Dictionary, operation_id: String, kind: String, arguments: Dictionary) -> Dictionary:
	return {
		"schema": "anima.lifecycle.world_action/0.1",
		"world_instance_id": obs["world_instance_id"],
		"epoch": obs["epoch"], "expected_revision": obs["revision"],
		"observation_id": obs["sample_id"], "operation_id": operation_id,
		"action_type": kind, "arguments": arguments,
	}


func _owner(obs: Dictionary) -> String:
	for reading in obs["readings"]:
		if reading["subject_ref"] == "lab.item.crate" and reading["predicate_ref"] == "owner":
			if reading["status"] == "known":
				return reading["value"]["value"]
			return reading["status"]
	return "unobserved"


func _finish(world: Node, ok: bool, reason: String = "") -> void:
	if is_instance_valid(world):
		world.free()
	if ok:
		print("LIFECYCLE_E1_3_NATIVE_PASS")
	else:
		printerr("LIFECYCLE_E1_3_NATIVE_FAIL: " + reason)
	quit(0 if ok else 1)


func _initialize() -> void:
	var world: Node = load("res://LifecycleWorld.gd").new()
	world._seed = 7
	world._effects_enabled = true
	world._reset_world()
	var hello := _call(world, 1, "agent", "hello")
	if not hello["ok"] or hello["data"]["capabilities"] != ["observe", "act"]:
		_finish(world, false, "opt-in capability not visible")
		return
	var first: Dictionary = _call(world, 2, "agent", "observe")["data"]
	var pick := _action(first, "op.native.pick", "world.pick", {"item_ref": "lab.item.crate"})
	var response := _call(world, 3, "agent", "act", {"action": pick})
	if not response["ok"] or response["data"]["status"] != "APPLIED" or response["data"]["revision"] != 1:
		_finish(world, false, "pick not applied with versioned receipt")
		return
	var holding: Dictionary = _call(world, 4, "agent", "observe")["data"]
	if _owner(holding) != "lab.actor.anima" or holding["self_position"] != {"x": 3, "y": 5}:
		_finish(world, false, "pick not reflected in independent sensor")
		return
	var duplicate := _call(world, 5, "agent", "act", {"action": pick})
	if duplicate["ok"] or duplicate["error"] != "OPERATION_REUSED":
		_finish(world, false, "duplicate effect not rejected")
		return
	var move := _action(holding, "op.native.move", "world.move", {"direction": "E"})
	var moved := _call(world, 6, "agent", "act", {"action": move})
	if not moved["ok"] or moved["data"]["status"] != "APPLIED":
		_finish(world, false, "move not applied")
		return
	var second: Dictionary = _call(world, 7, "agent", "observe")["data"]
	if second["self_position"] != {"x": 4, "y": 5} or _owner(second) != "lab.actor.anima":
		_finish(world, false, "moving did not move carried item")
		return
	var stale := _action(holding, "op.native.stale", "world.move", {"direction": "E"})
	var rejected := _call(world, 8, "agent", "act", {"action": stale})
	if rejected["ok"] or rejected["error"] != "STALE_REVISION":
		_finish(world, false, "stale world state accepted")
		return
	var invalid := _action(second, "op.native.fs", "fs.delete", {"path": "/etc"})
	var forbidden := _call(world, 9, "agent", "act", {"action": invalid})
	if forbidden["ok"] or forbidden["error"] != "INVALID_ACTION":
		_finish(world, false, "unknown tool escaped allowlist")
		return
	var operator := _call(world, 10, "operator", "act", {"action": move})
	if operator["ok"] or operator["error"] != "FORBIDDEN":
		_finish(world, false, "operator issued an agent action")
		return
	var drop := _action(second, "op.native.drop", "world.drop", {"item_ref": "lab.item.crate"})
	var released := _call(world, 11, "agent", "act", {"action": drop})
	if not released["ok"] or released["data"]["status"] != "APPLIED":
		_finish(world, false, "drop not applied")
		return
	var third: Dictionary = _call(world, 12, "agent", "observe")["data"]
	if _owner(third) != "absent":
		_finish(world, false, "drop sensor still claims ownership")
		return
	_finish(world, true)
