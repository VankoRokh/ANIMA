extends SceneTree
## Isolated UI presentation test; no world, protocol or Core behavior may change.


func _fail(lab: Node, reason: String) -> void:
	if is_instance_valid(lab):
		lab.free()
	printerr("VAL_UI_MODE_FAIL: " + reason)
	quit(1)


func _initialize() -> void:
	var lab = load("res://Main.gd").new()
	if lab == null:
		printerr("VAL_UI_MODE_FAIL: Main.gd not instantiated")
		quit(1)
		return
	lab._reset_world()
	lab._hud = Label.new()
	lab._diagnostics = Label.new()
	lab._guide = Label.new()
	lab.add_child(lab._hud)
	lab.add_child(lab._diagnostics)
	lab.add_child(lab._guide)
	var initial_epoch: int = lab._epoch
	var initial_revision: int = lab._revision
	var initial_tick: int = lab._tick
	var initial_events: int = lab._event_seq
	var initial_human: Vector2i = lab._human
	var initial_anima: Vector2i = lab._anima

	lab._set_ui_mode("normal")
	if lab._diagnostics.visible or not lab._guide.visible:
		_fail(lab, "normal mode exposed privileged diagnostics")
		return
	if lab._hud.text.contains("port:") or lab._hud.text.contains("Tick:"):
		_fail(lab, "normal HUD contains developer-only fields")
		return

	var f3 := InputEventKey.new()
	f3.keycode = KEY_F3
	f3.pressed = true
	lab._paused = true
	lab._unhandled_key_input(f3)
	if lab._ui_mode != "debug" or not lab._diagnostics.visible or lab._guide.visible:
		_fail(lab, "F3 cannot open diagnostics while world paused")
		return
	if not lab._diagnostics.text.contains("OPERATOR / WORLD TRUTH"):
		_fail(lab, "debug panel did not render truth")
		return
	lab._unhandled_key_input(f3)
	if lab._ui_mode != "normal" or lab._diagnostics.visible or not lab._guide.visible:
		_fail(lab, "second F3 did not restore normal mode")
		return

	lab._set_ui_mode("debug")
	var no_op := InputEventKey.new()
	no_op.keycode = KEY_F3
	no_op.pressed = true
	no_op.echo = true
	lab._unhandled_key_input(no_op)
	if lab._ui_mode != "debug":
		_fail(lab, "key repeat unexpectedly toggled mode")
		return
	lab._set_ui_mode("not_a_mode")
	if lab._ui_mode != "debug":
		_fail(lab, "invalid UI mode accepted")
		return
	lab._set_ui_mode("normal")
	if (
		lab._epoch != initial_epoch or lab._revision != initial_revision
		or lab._tick != initial_tick or lab._event_seq != initial_events
		or lab._human != initial_human or lab._anima != initial_anima
	):
		_fail(lab, "presentation toggle changed world state")
		return
	var denied: Dictionary = lab._request(JSON.stringify({
		"protocol": "val.bridge/0.2", "id": 11,
		"role": "agent", "op": "inspect",
	}))
	if denied["ok"] or denied["error"] != "FORBIDDEN":
		_fail(lab, "normal view weakened agent source boundary")
		return
	var permitted: Dictionary = lab._request(JSON.stringify({
		"protocol": "val.bridge/0.2", "id": 12,
		"role": "operator", "op": "inspect",
	}))
	if not permitted["ok"]:
		_fail(lab, "operator inspect disabled by normal mode")
		return
	lab.free()
	print("VAL_UI_MODE_PASS")
	quit(0)
