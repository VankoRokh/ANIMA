extends SceneTree
## Run with: godot --headless --path labs/virtual_anima_lab/godot \
##   --script res://BridgeProtocolTest.gd
## This exercises Godot's real JSON parser, not a Python-only mock.


func _initialize() -> void:
	var lab = load("res://Main.gd").new()
	if lab == null:
		printerr("VAL_BRIDGE_ID_CONTRACT_FAIL: Main.gd did not instantiate")
		quit(1)
		return
	var valid = [
		'{"protocol":"val.bridge/0.1","id":1,"role":"agent","op":"ping"}',
		'{"protocol":"val.bridge/0.1","id":2.0,"role":"agent","op":"ping"}',
	]
	for data in valid:
		var reply = lab._request(data)
		if not reply.get("ok", false):
			printerr("VAL_BRIDGE_ID_CONTRACT_FAIL: valid request rejected: ", reply)
			quit(1)
			return
		if typeof(reply.get("id")) != TYPE_INT:
			printerr("VAL_BRIDGE_ID_CONTRACT_FAIL: reply ID is not an int: ", reply)
			quit(1)
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
			printerr("VAL_BRIDGE_ID_CONTRACT_FAIL: invalid request accepted: ", reply)
			quit(1)
			return
	var restricted = lab._request(
		'{"protocol":"val.bridge/0.1","id":3,"role":"agent","op":"debug_snapshot"}'
	)
	if restricted.get("ok", false) or restricted.get("error") != "FORBIDDEN":
		printerr("VAL_BRIDGE_ID_CONTRACT_FAIL: role guard: ", restricted)
		quit(1)
		return
	print("VAL_BRIDGE_ID_CONTRACT_PASS: valid integer IDs normalized; invalid IDs rejected")
	quit(0)
