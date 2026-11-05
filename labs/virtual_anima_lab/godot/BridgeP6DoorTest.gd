extends SceneTree
## Headless parser/native contract: p6_door grants agent an adjacent door action.
## No Python bridge or ANIMA Core needed for this protocol-level smoke.

const WIRE := "val.bridge/0.2"


func _call(lab: Node, id: int, role: String, op: String, fields: Dictionary = {}) -> Dictionary:
	var req := {"protocol": WIRE, "id": id, "role": role, "op": op}
	for k in fields:
		req[k] = fields[k]
	return lab._request(JSON.stringify(req))


func _finish(lab: Node, ok: bool, reason: String) -> void:
	if is_instance_valid(lab):
		lab.free()
	if ok:
		print("VAL_P6_DOOR_PASS")
	else:
		printerr("VAL_P6_DOOR_FAIL: " + reason)
	quit(0 if ok else 1)


func _initialize() -> void:
	var lab = load("res://Main.gd").new()
	if lab == null:
		_finish(lab, false, "Main.gd could not be loaded")
		return
	lab._scenario = "p6_door"
	lab._reset_world()
	var hello := _call(lab, 1, "agent", "hello")
	if not hello["ok"] or not hello["data"]["capabilities"].has("act_door"):
		_finish(lab, false, "agent P6 action not registered")
		return
	if str(hello["data"]["world_instance_id"]).length() != 32:
		_finish(lab, false, "world instance ID missing")
		return
	if _call(lab, 2, "agent", "inspect")["error"] != "FORBIDDEN":
		_finish(lab, false, "agent gained world-truth access")
		return
	var before := _call(lab, 3, "agent", "observe")
	var found_open := false
	for reading in before["data"]["readings"]:
		if reading["subject_ref"] == "lab.door.01" and reading["typed_value"] == {
			"type": "symbol", "value": "open",
		}:
			found_open = true
	if not found_open:
		_finish(lab, false, "P6 fixture door not visible and open")
		return
	var arguments := {
		"operation_id": "p6:native:1",
		"action": {"schema": "val.door_action/0.1", "kind": "close_door"},
		"expected_epoch": before["epoch"],
		"expected_revision": before["revision"],
	}
	var first := _call(lab, 4, "agent", "act_door", arguments)
	if not first["ok"] or first["data"]["status"] != "APPLIED":
		_finish(lab, false, "close door failed")
		return
	var after := _call(lab, 5, "agent", "observe")
	var found_closed := false
	for reading in after["data"]["readings"]:
		if reading["subject_ref"] == "lab.door.01" and reading["typed_value"] == {
			"type": "symbol", "value": "closed",
		}:
			found_closed = true
	if not found_closed:
		_finish(lab, false, "independent observation did not show closed door")
		return
	var replay := _call(lab, 6, "agent", "act_door", arguments)
	if not replay["ok"] or not replay["data"]["replayed"]:
		_finish(lab, false, "operation was not replayed safely")
		return
	if replay["event_seq"] != first["event_seq"]:
		_finish(lab, false, "replay created additional effect event")
		return
	var status := _call(lab, 7, "agent", "door_operation_status", {
		"operation_id": "p6:native:1",
	})
	if not status["ok"] or not status["data"]["found"]:
		_finish(lab, false, "read-only operation lookup missing")
		return
	var conflict := arguments.duplicate(true)
	conflict["expected_revision"] = first["revision"]
	var collision := _call(lab, 8, "agent", "act_door", conflict)
	if collision["ok"] or collision["error"] != "OPERATION_ID_CONFLICT":
		_finish(lab, false, "operation key collision not rejected")
		return
	var stale := arguments.duplicate(true)
	stale["operation_id"] = "p6:native:stale"
	var rejected := _call(lab, 9, "agent", "act_door", stale)
	if rejected["ok"] or rejected["error"] != "STALE_WORLD":
		_finish(lab, false, "stale action was not rejected")
		return
	if _call(lab, 10, "agent", "set_door", {"open": true})["error"] != "FORBIDDEN":
		_finish(lab, false, "agent received operator privileges")
		return
	var reset := _call(lab, 11, "operator", "reset")
	if not reset["ok"] or reset["epoch"] != first["epoch"] + 1:
		_finish(lab, false, "world reset did not advance epoch")
		return
	_finish(lab, true, "")
