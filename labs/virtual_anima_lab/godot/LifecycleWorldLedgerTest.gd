extends SceneTree
## E1.4 native ledger acceptance; E1.3 & prior contracts must remain unchanged.
## No IO/network trust: use the Godot world directly to isolate effects and clocks.

func _call(world: Node, request_id: int, role: String, op: String, fields: Dictionary = {}) -> Dictionary:
	var request := {"protocol": "val.bridge/0.2", "id": request_id, "role": role, "op": op}
	for key in fields:
		request[key] = fields[key]
	return world._request(JSON.stringify(request))


func _action(obs: Dictionary, operation_id: String, direction: String) -> Dictionary:
	return {
		"schema": "anima.lifecycle.world_action/0.1",
		"world_instance_id": obs["world_instance_id"],
		"epoch": obs["epoch"], "expected_revision": obs["revision"],
		"observation_id": obs["sample_id"], "operation_id": operation_id,
		"action_type": "world.move", "arguments": {"direction": direction},
	}


func _status(world: Node, request_id: int, action: Dictionary) -> Dictionary:
	return _call(world, request_id, "agent", "operation_status", {
		"world_instance_id": action["world_instance_id"],
		"epoch": action["epoch"], "operation_id": action["operation_id"],
	})


func _expect(ok: bool, reason: String) -> bool:
	if not ok:
		printerr("LIFECYCLE_E1_4_NATIVE_FAIL: " + reason)
	return ok


func _finish(world: Node, ok: bool) -> void:
	if is_instance_valid(world):
		world.free()
	if ok:
		print("LIFECYCLE_E1_4_NATIVE_PASS")
	quit(0 if ok else 1)


func _initialize() -> void:
	var world: Node = load("res://LifecycleWorld.gd").new()
	world._seed = 7
	world._effects_enabled = true
	world._ledger_enabled = true
	world._reset_world()
	var h := _call(world, 1, "agent", "hello")
	if not _expect(h["ok"] and h["data"]["capabilities"] == ["observe", "act", "operation_status"], "opt-in ledger capabilities"):
		_finish(world, false)
		return
	var obs: Dictionary = _call(world, 2, "agent", "observe")["data"]
	var move := _action(obs, "e14.native.move", "E")
	var first := _call(world, 3, "agent", "act", {"action": move})
	var receipt: Dictionary = first["data"]
	if not _expect(first["ok"] and receipt["status"] == "APPLIED" and receipt["replayed"] == false, "first effect"):
		_finish(world, false)
		return
	var seq := world._event_seq
	var tick := world._tick
	var rev := world._revision
	var pos: Vector2i = world._anima
	# Different JSON key insertion order is still the same canonical action.
	var shuffled: Dictionary = {
		"operation_id": move["operation_id"], "arguments": {"direction": "E"},
		"action_type": move["action_type"], "observation_id": move["observation_id"],
		"expected_revision": move["expected_revision"], "epoch": move["epoch"],
		"world_instance_id": move["world_instance_id"], "schema": move["schema"],
	}
	var replay := _call(world, 4, "agent", "act", {"action": shuffled})
	var replayed: Dictionary = replay["data"]
	if not _expect(replay["ok"] and replayed["replayed"] and replayed["event_id"] == receipt["event_id"] and replayed["revision"] == receipt["revision"] and replayed["tick"] == receipt["tick"], "replay did not preserve original receipt"):
		_finish(world, false)
		return
	if not _expect(world._event_seq == seq and world._tick == tick and world._revision == rev and world._anima == pos, "replay changed world state or events"):
		_finish(world, false)
		return
	var conflict: Dictionary = move.duplicate(true)
	conflict["arguments"] = {"direction": "W"}
	var denied := _call(world, 5, "agent", "act", {"action": conflict})
	if not _expect(not denied["ok"] and denied["error"] == "OPERATION_CONFLICT", "same id / changed payload not rejected"):
		_finish(world, false)
		return
	var found := _status(world, 6, move)
	var data: Dictionary = found["data"]
	if not _expect(found["ok"] and data["schema"] == "anima.lifecycle.world_operation_status/0.1" and data["status"] == "RECORDED" and data["receipt"] == receipt, "status did not return original receipt"):
		_finish(world, false)
		return
	if not _expect(world._event_seq == seq and world._tick == tick, "status changed world clocks"):
		_finish(world, false)
		return
	var unknown: Dictionary = move.duplicate(true)
	unknown["operation_id"] = "e14.missing"
	var missing := _status(world, 7, unknown)
	if not _expect(missing["ok"] and missing["data"]["status"] == "UNKNOWN" and missing["data"]["receipt"] == null, "missing entry falsely claimed no effect"):
		_finish(world, false)
		return
	var operator := _call(world, 8, "operator", "operation_status", {
		"world_instance_id": move["world_instance_id"], "epoch": move["epoch"], "operation_id": move["operation_id"],
	})
	if not _expect(not operator["ok"], "operator queried agent ledger"):
		_finish(world, false)
		return
	# BLOCKED receives a terminal receipt and may be replayed, never reattempted.
	world._anima = Vector2i(5, 5)
	var at_wall: Dictionary = _call(world, 9, "agent", "observe")["data"]
	var blocked := _action(at_wall, "e14.blocked", "E")
	var no_effect := _call(world, 10, "agent", "act", {"action": blocked})
	if not _expect(no_effect["ok"] and no_effect["data"]["status"] == "BLOCKED" and not no_effect["data"]["effect_applied"], "blocked receipt absent"):
		_finish(world, false)
		return
	var before_replay_tick := world._tick
	var blocked_replay := _call(world, 11, "agent", "act", {"action": blocked})
	if not _expect(blocked_replay["ok"] and blocked_replay["data"]["replayed"] and blocked_replay["data"]["status"] == "BLOCKED" and world._tick == before_replay_tick, "blocked action retried"):
		_finish(world, false)
		return
	# Fully populate without evicting known events. Capacity must fail-closed.
	for i in range(world.MAX_E14_LEDGER_ENTRIES - 2):
		var sample: Dictionary = _call(world, 1000 + i * 2, "agent", "observe")["data"]
		var act := _action(sample, "e14.fill.%03d" % i, "E")
		var result := _call(world, 1001 + i * 2, "agent", "act", {"action": act})
		if not _expect(result["ok"] and result["data"]["status"] == "BLOCKED", "fill not blocked at index %d" % i):
			_finish(world, false)
			return
	var full_sample: Dictionary = _call(world, 2001, "agent", "observe")["data"]
	var extra := _action(full_sample, "e14.capacity.extra", "E")
	var cap := _call(world, 2002, "agent", "act", {"action": extra})
	if not _expect(not cap["ok"] and cap["error"] == "OPERATION_CAPACITY" and world._operation_ledger.size() == world.MAX_E14_LEDGER_ENTRIES, "capacity failed open"):
		_finish(world, false)
		return
	var old_replay := _call(world, 2003, "agent", "act", {"action": move})
	if not _expect(old_replay["ok"] and old_replay["data"]["replayed"], "full ledger lost existing replay"):
		_finish(world, false)
		return
	var old_status := _status(world, 2004, move)
	if not _expect(old_status["ok"] and old_status["data"]["status"] == "RECORDED", "full ledger lost old status"):
		_finish(world, false)
		return
	# New epoch must not reveal or replay pre-reset records.
	var old_epoch := world._epoch
	world._reset_world()
	if not _expect(world._epoch == old_epoch + 1 and world._operation_ledger.is_empty(), "epoch reset did not clear scoped ledger"):
		_finish(world, false)
		return
	var lost := _status(world, 2005, move)
	if not _expect(lost["ok"] and lost["data"]["status"] == "UNKNOWN", "old epoch receipt leaked after reset"):
		_finish(world, false)
		return
	var late := _call(world, 2006, "agent", "act", {"action": move})
	if not _expect(not late["ok"] and late["error"] == "EPOCH_CHANGED", "old intent executed in new epoch"):
		_finish(world, false)
		return
	_finish(world, true)
