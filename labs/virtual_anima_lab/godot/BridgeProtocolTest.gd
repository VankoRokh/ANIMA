extends SceneTree
## Run with: godot --headless --path labs/virtual_anima_lab/godot \
##   --script res://BridgeProtocolTest.gd
## This exercises Godot's real JSON parser, not a Python-only mock.


func _finish(lab: Node, passed: bool, message: String) -> void:
	# _initialize() creates an off-tree Node2D; SceneTree does not own it.
	# Explicitly release its CanvasItem RID and script references before exit.
	if is_instance_valid(lab):
		lab.free()
	if passed:
		print(message)
	else:
		printerr(message)
	quit(0 if passed else 1)


func _initialize() -> void:
	var lab = load("res://Main.gd").new()
	if lab == null:
		_finish(lab, false, "VAL_BRIDGE_ID_CONTRACT_FAIL: Main.gd did not instantiate")
		return
	var valid = [
		'{"protocol":"val.bridge/0.1","id":1,"role":"agent","op":"ping"}',
		'{"protocol":"val.bridge/0.1","id":2.0,"role":"agent","op":"ping"}',
	]
	for data in valid:
		var reply = lab._request(data)
		if not reply.get("ok", false):
			_finish(lab, false, "VAL_BRIDGE_ID_CONTRACT_FAIL: valid request rejected: %s" % str(reply))
			return
		if typeof(reply.get("id")) != TYPE_INT:
			_finish(lab, false, "VAL_BRIDGE_ID_CONTRACT_FAIL: reply ID is not an int: %s" % str(reply))
			return
	var invalid = [
		'{"protocol":"val.bridge/0.1","id":1.5,"role":"agent","op":"ping"}',
		'{"protocol":"val.bridge/0.1","id":-1,"role":"agent","op":"ping"}',
		'{"protocol":"val.bridge/0.1","id":"1","role":"agent","op":"ping"}',
		'{"protocol":"val.bridge/0.1","id":true,"role":"agent","op":"ping"}',
		'{"protocol":"val.bridge/0.1","id":2147483648,"role":"agent","op":"ping"}',
	]
	for data in invalid:
		var reply = lab._request(data)
		if reply.get("ok", false) or reply.get("error") != "INVALID_ID":
			_finish(lab, false, "VAL_BRIDGE_ID_CONTRACT_FAIL: invalid request accepted: %s" % str(reply))
			return
	var restricted = lab._request(
		'{"protocol":"val.bridge/0.1","id":3,"role":"agent","op":"debug_snapshot"}'
	)
	if restricted.get("ok", false) or restricted.get("error") != "FORBIDDEN":
		_finish(lab, false, "VAL_BRIDGE_ID_CONTRACT_FAIL: role guard: %s" % str(restricted))
		return
	_finish(lab, true, "VAL_BRIDGE_ID_CONTRACT_PASS: valid integer IDs normalized; invalid IDs rejected")
