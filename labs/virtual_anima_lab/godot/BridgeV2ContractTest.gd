extends SceneTree
## Real Godot parser/contract checks, no TCP or ANIMA Core required.
## godot --headless --path labs/virtual_anima_lab/godot \
##   --script res://BridgeV2ContractTest.gd

const WIRE := "val.bridge/0.2"


func _call(lab: Node, id: int, role: String, op: String, fields: Dictionary = {}) -> Dictionary:
	var request := {"protocol": WIRE, "id": id, "role": role, "op": op}
	for key in fields:
		request[key] = fields[key]
	return lab._request(JSON.stringify(request))


func _finish(lab: Node, ok: bool, reason: String) -> void:
	if is_instance_valid(lab):
		lab.free()
	if ok:
		print("VAL_BRIDGE_V2_CONTRACT_PASS")
	else:
		printerr("VAL_BRIDGE_V2_CONTRACT_FAIL: " + reason)
	quit(0 if ok else 1)


func _initialize() -> void:
	var lab = load("res://Main.gd").new()
	if lab == null:
		_finish(lab, false, "cannot instantiate Main.gd")
		return
	lab._reset_world()
	var hello := _call(lab, 1, "agent", "hello")
	if not hello["ok"] or hello["data"]["action_schema"] != "val.action/0.1":
		_finish(lab, false, "version handshake")
		return
	var obs := _call(lab, 2, "agent", "observe")
	if not obs["ok"] or obs["data"]["source_ref"] != "lab.sensor.anima.proximity":
		_finish(lab, false, "typed observation")
		return
	if _call(lab, 3, "agent", "inspect")["error"] != "FORBIDDEN":
		_finish(lab, false, "privileged debug leaked to agent")
		return
	var unsupported = lab._request(
		'{"protocol":"val.bridge/9.0","id":14,"role":"agent","op":"hello"}'
	)
	if unsupported["ok"] or unsupported["error"] != "UNSUPPORTED_PROTOCOL":
		_finish(lab, false, "unsupported wire version was not rejected")
		return
	var malformed := _call(lab, 15, "agent", "act", {
		"operation_id": "bad?key",
		"action": {"schema": "val.action/0.1", "direction": "E"},
		"expected_epoch": 1, "expected_revision": 0,
	})
	if malformed["ok"] or malformed["error"] != "INVALID_OPERATION_ID":
		_finish(lab, false, "invalid operation key was accepted")
		return
	var first := _call(lab, 4, "agent", "act", {
		"operation_id": "test:step:1",
		"action": {"schema": "val.action/0.1", "direction": "W"},
		"expected_epoch": 1, "expected_revision": 0,
	})
	if not first["ok"] or not first["data"]["effect_applied"]:
		_finish(lab, false, "first action did not apply")
		return
	var replay := _call(lab, 5, "agent", "act", {
		"operation_id": "test:step:1",
		"action": {"schema": "val.action/0.1", "direction": "W"},
		"expected_epoch": 1, "expected_revision": 0,
	})
	if not replay["ok"] or not replay["data"]["replayed"]:
		_finish(lab, false, "same operation not replayed")
		return
	if replay["event_seq"] != first["event_seq"]:
		_finish(lab, false, "duplicate operation wrote a second event")
		return
	var conflict := _call(lab, 6, "agent", "act", {
		"operation_id": "test:step:1",
		"action": {"schema": "val.action/0.1", "direction": "E"},
		"expected_epoch": 1, "expected_revision": 0,
	})
	if conflict["ok"] or conflict["error"] != "OPERATION_ID_CONFLICT":
		_finish(lab, false, "same key with different request not rejected")
		return
	var stale := _call(lab, 7, "agent", "act", {
		"operation_id": "test:stale",
		"action": {"schema": "val.action/0.1", "direction": "E"},
		"expected_epoch": 1, "expected_revision": 0,
	})
	if stale["ok"] or stale["error"] != "STALE_WORLD":
		_finish(lab, false, "outdated revision was accepted")
		return
	var inspect := _call(lab, 8, "operator", "inspect")
	if inspect["data"]["anima"]["x"] != 8 or inspect["revision"] != 1:
		_finish(lab, false, "duplicate changed world position or revision")
		return
	var events := _call(lab, 9, "operator", "events", {"after_seq": 0, "limit": 8})
	if not events["ok"] or events["data"]["events"].size() < 2:
		_finish(lab, false, "paged event history missing")
		return
	var before_reset: int = inspect["epoch"]
	_call(lab, 10, "operator", "reset")
	var after_reset := _call(lab, 11, "operator", "inspect")
	if after_reset["epoch"] != before_reset + 1 or after_reset["revision"] != 0:
		_finish(lab, false, "world epoch/reset invalid")
		return
	var replay_old := _call(lab, 12, "agent", "act", {
		"operation_id": "test:step:1",
		"action": {"schema": "val.action/0.1", "direction": "W"},
		"expected_epoch": 1, "expected_revision": 0,
	})
	if replay_old["ok"] or replay_old["error"] != "STALE_WORLD":
		_finish(lab, false, "old-epoch command was accepted")
		return
	_finish(lab, true, "")
