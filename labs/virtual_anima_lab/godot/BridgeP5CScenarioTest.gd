extends SceneTree
## Native Godot test of P5-C operator-only fixtures and scenario geometry.
## godot --headless --path labs/virtual_anima_lab/godot \
##   --script res://BridgeP5CScenarioTest.gd


func _call(lab: Node, req_id: int, role: String, op: String, args: Dictionary = {}) -> Dictionary:
	var request = {
		"protocol": "val.bridge/0.2", "id": req_id, "role": role, "op": op,
	}
	for key in args:
		request[key] = args[key]
	return lab._request(JSON.stringify(request))


func _finish(lab: Node, good: bool, message: String = "") -> void:
	if is_instance_valid(lab):
		lab.free()
	if good:
		print("VAL_P5C_SCENARIO_CONTRACT_PASS")
	else:
		printerr("VAL_P5C_SCENARIO_CONTRACT_FAIL: " + message)
	quit(0 if good else 1)


func _initialize() -> void:
	var lab = load("res://Main.gd").new()
	if lab == null:
		_finish(lab, false, "Main.gd could not instantiate")
		return
	lab._reset_world()
	var hello := _call(lab, 1, "operator", "hello")
	if not hello["ok"] or hello["data"]["scenario"] != "base":
		_finish(lab, false, "base scenario handshake")
		return
	var forbidden := _call(lab, 2, "agent", "set_obstacle", {
		"at": {"x": 10, "y": 5}, "blocked": true,
	})
	if forbidden["ok"] or forbidden["error"] != "FORBIDDEN":
		_finish(lab, false, "agent changed operator-owned obstacle")
		return
	var invalid := _call(lab, 3, "operator", "set_obstacle", {
		"at": {"x": 999, "y": 5}, "blocked": true,
	})
	if invalid["ok"] or invalid["error"] != "INVALID_OBSTACLE_CELL":
		_finish(lab, false, "bad grid coordinate accepted")
		return
	var blocked := _call(lab, 4, "operator", "set_obstacle", {
		"at": {"x": 10, "y": 5}, "blocked": true,
	})
	if not blocked["ok"] or blocked["revision"] != 1:
		_finish(lab, false, "obstacle did not change world revision")
		return
	var observed := _call(lab, 5, "agent", "observe")
	var visible := false
	for item in observed["data"]["readings"]:
		if item["subject_ref"] == "lab.obstacle.10.5":
			visible = true
	if not visible:
		_finish(lab, false, "sensor did not see obstacle")
		return
	var before_noise: int = blocked["revision"]
	var noise := _call(lab, 6, "operator", "emit_noise", {"label": "fan_hum"})
	if not noise["ok"] or noise["revision"] != before_noise:
		_finish(lab, false, "noise improperly changed world revision")
		return
	var audit := _call(lab, 12, "operator", "events", {
		"after_seq": 0, "limit": 8,
	})
	var noise_logged := false
	for entry in audit["data"]["events"]:
		if (
			entry["actor"] == "ambient" and entry["event"] == "noise"
			and entry["details"]["label"] == "fan_hum"
		):
			noise_logged = true
	if not audit["ok"] or not noise_logged:
		_finish(lab, false, "operator ambient noise absent from event log")
		return
	var after_noise := _call(lab, 13, "agent", "observe")
	for reading in after_noise["data"]["readings"]:
		if reading["subject_ref"].begins_with("lab.noise"):
			_finish(lab, false, "operator-authored ambient event leaked as agent belief")
			return
	var bad_noise := _call(lab, 14, "operator", "emit_noise", {"label": "bad label"})
	if bad_noise["ok"] or bad_noise["error"] != "INVALID_NOISE_LABEL":
		_finish(lab, false, "unbounded or malformed noise label accepted")
		return
	var attempted := _call(lab, 7, "agent", "act", {
		"operation_id": "p5c:blocked:01",
		"action": {"schema": "val.action/0.1", "direction": "E"},
		"expected_epoch": 1, "expected_revision": 1,
	})
	if not attempted["ok"] or attempted["data"]["status"] != "BLOCKED":
		_finish(lab, false, "obstacle collision not enforced")
		return
	var removed := _call(lab, 8, "operator", "set_obstacle", {
		"at": {"x": 10, "y": 5}, "blocked": false,
	})
	if not removed["ok"] or removed["revision"] != 2:
		_finish(lab, false, "obstacle removal failed")
		return
	var actor_change := _call(lab, 9, "operator", "human_move", {
		"direction": "E",
	})
	if not actor_change["ok"] or actor_change["revision"] != 3:
		_finish(lab, false, "human intervention not versioned")
		return
	var stale := _call(lab, 10, "agent", "act", {
		"operation_id": "p5c:stale:01",
		"action": {"schema": "val.action/0.1", "direction": "E"},
		"expected_epoch": 1, "expected_revision": 1,
	})
	if stale["ok"] or stale["error"] != "STALE_WORLD":
		_finish(lab, false, "stale action after intervention accepted")
		return
	lab._scenario = "detour"
	lab._reset_world()
	if lab._epoch != 2 or Vector2i(7, 4) not in lab._walls:
		_finish(lab, false, "detour profile did not reset to new geometry")
		return
	lab._scenario = "clutter"
	lab._reset_world()
	if lab._epoch != 3 or Vector2i(8, 3) not in lab._walls:
		_finish(lab, false, "clutter profile did not reset to new geometry")
		return
	var no_truth := _call(lab, 11, "agent", "inspect")
	if no_truth["ok"] or no_truth["error"] != "FORBIDDEN":
		_finish(lab, false, "world truth leaked to agent role")
		return
	_finish(lab, true)
