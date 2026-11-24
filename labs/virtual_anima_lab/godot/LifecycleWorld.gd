extends Node2D
## Isolated lifecycle world; NEVER replaces the P5/P6 Main scene.
## Default: E1.2 observe-only; E1.3 world effects require explicit --lifecycle-effects.
## E2.1 guarded mode additionally requires distinct bearer capabilities for sensor,
## executor and operator. It is lab-only, not OS sandboxing or Core action admission.

const PROTOCOL := "val.bridge/0.2"
const OBSERVATION_SCHEMA := "anima.lifecycle.world_observation/0.1"
const VIEW_SCHEMA := "anima.lifecycle.egocentric_observation/0.1"
const VIEW_ACTION_SCHEMA := "anima.lifecycle.egocentric_action/0.1"
const VIEW_FOV_DEGREES := 90
const ACTION_SCHEMA := "anima.lifecycle.world_action/0.1"
const RECEIPT_SCHEMA := "anima.lifecycle.world_receipt/0.1"
const OPERATION_STATUS_SCHEMA := "anima.lifecycle.world_operation_status/0.1"
const E25C_FIXTURE_RECEIPT := "anima.lifecycle.operator_fixture_receipt/0.1"
const WORLD_VERSION := "lifecycle-grid/0.1"
const WIDTH := 14
const HEIGHT := 11
const CELL := 48
const SENSE_RADIUS := 3
const MAX_LINE_BYTES := 8192
const MAX_DYNAMIC_OBSTACLES := 8
const MAX_E13_OPERATIONS := 256
const MAX_E14_LEDGER_ENTRIES := 256

var _server: TCPServer = TCPServer.new()
var _peer: StreamPeerTCP = null
var _buffer := ""
var _port := 46029
var _seed := 7
var _effects_enabled := false
# E1.4 is a separate opt-in; default E1.2 and E1.3 contracts stay unchanged.
var _ledger_enabled := false
var _guarded := false
var _egocentric := false
var _e25c_fixtures := false # Operator-only and explicit opt-in; never agent-visible.
var _fixture_ledger: Dictionary = {}
var _debug_ui_enabled := false # Human-only. Never enters agent DTO or Core context.
var _visual_control_port := 0
var _visual_control_token := ""
var _visual_state: Dictionary = {}
var _visual_error := "Controller offline"
var _configuration_ok := true
# Distinct ephemeral secrets from the trusted harness environment, not argv or hello.
var _observer_key := ""
var _executor_key := ""
var _operator_key := ""
var _used_operations: Dictionary = {}  # E1.3 legacy: reject duplicates, no replay
var _operation_ledger: Dictionary = {}  # E1.4: in-memory, bounded, epoch scoped
var _item_owner := ""
var _world_instance_id := Crypto.new().generate_random_bytes(16).hex_encode()
var _epoch := 0
var _revision := 0
var _tick := 0
var _sample_seq := 0
var _event_seq := 0
var _walls: Array[Vector2i] = []
var _obstacles: Array[Vector2i] = []
var _shortcut := Vector2i.ZERO
var _anima := Vector2i.ZERO
var _facing := Vector2i(0, -1)
var _opaque_refs: Dictionary = {}
var _item := Vector2i.ZERO
var _delivery := Vector2i.ZERO
var _landmark := Vector2i.ZERO
var _scenario: Dictionary = {}
var _history: Array[Dictionary] = []
var _last_sample: Dictionary = {}
var _status: Label = null
var _debug_panel: Label = null


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_parse_args()
	if not _configuration_ok:
		return
	_reset_world()
	_status = Label.new()
	_status.position = Vector2(14, HEIGHT * CELL + 12)
	_status.add_theme_font_size_override("font_size", 16)
	add_child(_status)
	_refresh_status()
	if _debug_ui_enabled:
		_build_debug_panel()
	if _visual_control_port > 0:
		var visual_script: Script = load("res://VisualControlHUD.gd")
		var visual: Control = visual_script.new()
		visual.position = Vector2(WIDTH * CELL + 7, HEIGHT * CELL + 6)
		visual.call("configure", _visual_control_port, _visual_control_token)
		add_child(visual)
	var listen_error := _server.listen(_port, "127.0.0.1")
	if listen_error != OK:
		push_error("Lifecycle World: cannot bind loopback port %d" % _port)
		get_tree().quit(2)
		return
	if _guarded:
		print("ANIMA_LIFECYCLE_WORLD_READY protocol=%s port=%d guarded=true" % [PROTOCOL, _port])
	else:
		print("ANIMA_LIFECYCLE_WORLD_READY protocol=%s port=%d seed=%d" % [PROTOCOL, _port, _seed])


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if args[index] == "--lifecycle-port" and index + 1 < args.size():
			_port = int(args[index + 1])
			index += 1
		elif args[index] == "--lifecycle-seed" and index + 1 < args.size():
			_seed = int(args[index + 1])
			index += 1
		elif args[index] == "--lifecycle-effects":
			_effects_enabled = true
		elif args[index] == "--lifecycle-ledger":
			_ledger_enabled = true
		elif args[index] == "--lifecycle-guarded":
			_guarded = true
		elif args[index] == "--lifecycle-egocentric":
			_egocentric = true
		elif args[index] == "--lifecycle-e25c-fixtures":
			_e25c_fixtures = true
		elif args[index] == "--lifecycle-debug-ui":
			_debug_ui_enabled = true
		elif args[index] == "--lifecycle-visual-control-port" and index + 1 < args.size():
			_visual_control_port = int(args[index + 1])
			index += 1
		index += 1
	if _guarded:
		_observer_key = OS.get_environment("ANIMA_LIFECYCLE_OBSERVER_KEY")
		_executor_key = OS.get_environment("ANIMA_LIFECYCLE_EXECUTOR_KEY")
		_operator_key = OS.get_environment("ANIMA_LIFECYCLE_OPERATOR_KEY")
		var key_pattern := RegEx.create_from_string("^[A-Za-z0-9_-]{32,128}$")
		if (_observer_key == _executor_key or _observer_key == _operator_key
				or _executor_key == _operator_key
				or key_pattern.search(_observer_key) == null
				or key_pattern.search(_executor_key) == null
				or key_pattern.search(_operator_key) == null):
			_configuration_ok = false
			push_error("Lifecycle World: guarded mode requires three distinct strong keys")
			get_tree().quit(2)
			return
	if _egocentric and not _guarded:
		_configuration_ok = false
		push_error("Lifecycle World: egocentric sensor requires guarded role separation")
		get_tree().quit(2)
		return
	if _e25c_fixtures and not (_guarded and _egocentric and _effects_enabled and _ledger_enabled):
		_configuration_ok = false
		push_error("Lifecycle World: E2.5c fixture requires full guarded egocentric mode")
		get_tree().quit(2)
		return
	if _visual_control_port != 0:
		_visual_control_token = OS.get_environment("ANIMA_VISUAL_CONTROL_KEY")
		var control_pattern := RegEx.create_from_string("^[A-Za-z0-9_-]{32,128}$")
		if (not _guarded or not _egocentric or not _effects_enabled
				or not _ledger_enabled or not _debug_ui_enabled
				or _visual_control_port < 1024 or _visual_control_port > 65535
				or _visual_control_port == _port
				or control_pattern.search(_visual_control_token) == null
				or _visual_control_token in [_observer_key, _executor_key, _operator_key]):
			_configuration_ok = false
			push_error("Lifecycle World: visual control requires a separate secured loopback endpoint")
			get_tree().quit(2)
			return
	if _ledger_enabled and not _effects_enabled:
		_configuration_ok = false
		push_error("Lifecycle World: ledger requires --lifecycle-effects")
		get_tree().quit(2)
		return
	if _guarded and _effects_enabled and not _ledger_enabled:
		_configuration_ok = false
		push_error("Lifecycle World: guarded execution requires operation ledger")
		get_tree().quit(2)
		return
	if _port < 1024 or _port > 65535 or _seed < 0 or _seed > 2147483647:
		_configuration_ok = false
		push_error("Lifecycle World: invalid port/seed")
		get_tree().quit(2)


func _point(raw: Array) -> Vector2i:
	return Vector2i(int(raw[0]), int(raw[1]))


func _cell(point: Vector2i) -> Dictionary:
	return {"x": point.x, "y": point.y}


func _inside(point: Vector2i) -> bool:
	return point.x >= 0 and point.y >= 0 and point.x < WIDTH and point.y < HEIGHT


func _blocked(point: Vector2i) -> bool:
	return point in _walls or point == _shortcut or point in _obstacles


func _record(actor: String, event: String, details: Dictionary) -> void:
	_event_seq += 1
	_history.append({
		"event_id": "lifecycle_evt:%d" % _event_seq,
		"event_seq": _event_seq, "world_instance_id": _world_instance_id,
		"epoch": _epoch, "revision": _revision, "tick": _tick,
		"actor": actor, "event": event, "details": details.duplicate(true),
	})
	if _history.size() > 64:
		_history.pop_front()


func _reset_world() -> void:
	# Same process identity; reset changes epoch; sample/event IDs never rewind.
	var parsed = JSON.parse_string(FileAccess.get_file_as_string("res://LifecycleScenario.json"))
	if typeof(parsed) != TYPE_DICTIONARY or parsed.get("schema") != "anima.lifecycle.world_scenario/0.1":
		push_error("Lifecycle World: invalid scenario fixture")
		return
	_scenario = parsed
	if int(_scenario["width"]) != WIDTH or int(_scenario["height"]) != HEIGHT:
		push_error("Lifecycle World: wrong fixture dimensions")
		return
	_epoch += 1
	# A new epoch is a new operation namespace. Old-epoch receipts are unavailable.
	_used_operations.clear()
	_operation_ledger.clear()
	_fixture_ledger.clear()
	_revision = 0
	_tick = 0
	_last_sample.clear()
	_history.clear()
	_facing = Vector2i(0, -1)
	_opaque_refs.clear()
	_walls.clear()
	_obstacles.clear()
	var partition: Dictionary = _scenario["partition"]
	# Godot JSON may represent numeric literals as floats. Normalize gate coords.
	var gaps: Array[int] = []
	for raw_gate in partition["open_y"]:
		gaps.append(int(raw_gate))
	for x in range(WIDTH):
		_walls.append(Vector2i(x, 0))
		_walls.append(Vector2i(x, HEIGHT - 1))
	for y in range(1, HEIGHT - 1):
		_walls.append(Vector2i(0, y))
		_walls.append(Vector2i(WIDTH - 1, y))
		if not (y in gaps):
			_walls.append(Vector2i(int(partition["x"]), y))
	_shortcut = _point(_scenario["shortcut_blocker"])
	var choices: Array = _scenario["seeded_obstacles"]
	_obstacles.append(_point(choices[_seed % choices.size()]))
	_anima = _point(_scenario["actor_start"])
	_item = _point(_scenario["item"]["at"])
	_item_owner = ""
	_delivery = _point(_scenario["delivery"]["at"])
	_landmark = _point(_scenario["landmark"]["at"])
	_record("harness", "reset", {"seed": _seed, "world_version": WORLD_VERSION})
	_refresh_status()
	queue_redraw()


# Sensor has a limited range and checks every intermediate occupied grid cell.
# Never use _inspect() to construct an agent observation.
func _visible(point: Vector2i) -> bool:
	var dx := point.x - _anima.x
	var dy := point.y - _anima.y
	if absi(dx) + absi(dy) > SENSE_RADIUS:
		return false
	var steps: int = maxi(absi(dx), absi(dy)) * 16
	if steps == 0:
		return true
	for index in range(1, steps):
		var fraction := float(index) / float(steps)
		var sampled := Vector2i(
			floori(float(_anima.x) + 0.5 + float(dx) * fraction),
			floori(float(_anima.y) + 0.5 + float(dy) * fraction)
		)
		if sampled == point:
			return true
		if _blocked(sampled):
			return false
	return true


func _reading(ref: String, predicate: String, status: String, value: Variant, at: Vector2i) -> Dictionary:
	return {
		"subject_ref": ref, "predicate_ref": predicate,
		"status": status, "value": value, "cell": _cell(at),
	}


func _position_value(point: Vector2i) -> Dictionary:
	return {"type": "grid_cell", "x": point.x, "y": point.y}


func _observation() -> Dictionary:
	# Increment sample_seq even if time and world_revision did not change.
	_sample_seq += 1
	var readings: Array[Dictionary] = []
	for wall in _walls:
		if _visible(wall):
			readings.append(_reading(
				"lab.wall.%d.%d" % [wall.x, wall.y], "position", "known",
				_position_value(wall), wall
			))
	if _visible(_shortcut):
		readings.append(_reading(
			"lab.obstacle.shortcut", "position", "known",
			_position_value(_shortcut), _shortcut
		))
	for obstacle in _obstacles:
		if _visible(obstacle):
			readings.append(_reading(
				"lab.obstacle.%d.%d" % [obstacle.x, obstacle.y], "position", "known",
				_position_value(obstacle), obstacle
			))
	if _visible(_item):
		readings.append(_reading(
			"lab.item.crate", "position", "known", _position_value(_item), _item
		))
		if _item_owner == "":
			readings.append(_reading("lab.item.crate", "owner", "absent", null, _item))
		else:
			readings.append(_reading("lab.item.crate", "owner", "known",
				{"type": "ref", "value": _item_owner}, _item))
	if _visible(_delivery):
		readings.append(_reading(
			"lab.zone.delivery", "position", "known",
			_position_value(_delivery), _delivery
		))
	if _visible(_landmark):
		readings.append(_reading(
			"lab.landmark.right", "position", "known",
			_position_value(_landmark), _landmark
		))
	var sample_id := "worldobs:%s:%d:%d" % [_world_instance_id, _epoch, _sample_seq]
	var sample := {
		"schema": OBSERVATION_SCHEMA,
		"world_instance_id": _world_instance_id,
		"epoch": _epoch, "revision": _revision,
		"tick": _tick, "sample_seq": _sample_seq, "sample_id": sample_id,
		"observer_ref": "lab.actor.anima",
		"source_ref": "lab.sensor.anima.proximity",
		"visibility": {"kind": "line_of_sight", "radius": SENSE_RADIUS},
		"self_position": _cell(_anima), "readings": readings,
	}
	_last_sample = sample.duplicate(true)
	_refresh_status()
	return sample



# E2.3 directed actor-relative sensor: never call _inspect() or reveal absolute
# coordinates, compass heading, or wall.x.y IDs to the observer.
func _view_visible(point: Vector2i) -> bool:
	var delta := point - _anima
	if delta == Vector2i.ZERO:
		return false
	var forward: int = delta.x * _facing.x + delta.y * _facing.y
	var right := delta.x * (-_facing.y) + delta.y * _facing.x
	if forward <= 0:
		return false
	if absf(rad_to_deg(atan2(float(right), float(forward)))) > float(VIEW_FOV_DEGREES) / 2.0:
		return false
	var steps: int = maxi(absi(delta.x), absi(delta.y)) * 16
	for index in range(1, steps):
		var fraction := float(index) / float(steps)
		var sampled := Vector2i(
			floori(float(_anima.x) + 0.5 + float(delta.x) * fraction),
			floori(float(_anima.y) + 0.5 + float(delta.y) * fraction)
		)
		if sampled == point:
			return true
		if _blocked(sampled):
			return false
	return true


func _opaque_ref(point: Vector2i, category: String) -> String:
	var key := "%s:%d:%d" % [category, point.x, point.y]
	if not _opaque_refs.has(key):
		_opaque_refs[key] = "lab.%s.%s" % [
			category, Crypto.new().generate_random_bytes(12).hex_encode()
		]
	return _opaque_refs[key]


func _view_reading(ref: String, category: String, point: Vector2i, properties: Dictionary = {}) -> Dictionary:
	var delta := point - _anima
	var forward: int = delta.x * _facing.x + delta.y * _facing.y
	var right := delta.x * (-_facing.y) + delta.y * _facing.x
	return {
		"entity_ref": ref, "category": category,
		"bearing_mdeg": roundi(rad_to_deg(atan2(float(right), float(forward))) * 1000.0),
		"range_milli_cells": roundi(sqrt(float(delta.x * delta.x + delta.y * delta.y)) * 1000.0),
		"properties": properties,
	}


func _observation_view() -> Dictionary:
	_sample_seq += 1
	var readings: Array[Dictionary] = []
	for wall in _walls:
		if _view_visible(wall):
			readings.append(_view_reading(_opaque_ref(wall, "surface"), "surface", wall))
	if _view_visible(_shortcut):
		readings.append(_view_reading("lab.obstacle.shortcut", "obstacle", _shortcut))
	for obstacle in _obstacles:
		if _view_visible(obstacle):
			readings.append(_view_reading(
				_opaque_ref(obstacle, "obstacle"), "obstacle", obstacle
			))
	if _view_visible(_item):
		var owner := {
			"status": "absent" if _item_owner == "" else "known",
			"value": null if _item_owner == "" else _item_owner,
		}
		readings.append(_view_reading("lab.item.crate", "item", _item, {"owner": owner}))
	if _view_visible(_delivery):
		readings.append(_view_reading("lab.zone.delivery", "zone", _delivery))
	if _view_visible(_landmark):
		readings.append(_view_reading("lab.landmark.marker", "landmark", _landmark))
	var sample_id := "worldobs:%s:%d:%d" % [_world_instance_id, _epoch, _sample_seq]
	var sample := {
		"schema": VIEW_SCHEMA,
		"world_instance_id": _world_instance_id, "epoch": _epoch,
		"revision": _revision, "tick": _tick,
		"sample_seq": _sample_seq, "sample_id": sample_id,
		"observer_ref": "lab.actor.anima", "source_ref": "lab.sensor.anima.vision",
		"coverage": {
			"kind": "view_cone", "fov_degrees": VIEW_FOV_DEGREES,
			"range_limit": "none", "occlusion": "opaque_grid_cells",
		},
		"readings": readings,
	}
	_last_sample = sample.duplicate(true)
	_refresh_status()
	return sample


# E1.3 experimental world effects: the world validates the DTO independently of Python.
# No goal/task authority is accepted here. Operator cannot use agent act.
func _valid_ref(value: Variant) -> bool:
	if typeof(value) != TYPE_STRING:
		return false
	var matcher := RegEx.create_from_string("^[A-Za-z][A-Za-z0-9._:/-]{0,127}$")
	return matcher.search(value) != null


func _valid_e13_action(req: Dictionary) -> bool:
	if req.size() != 5 or typeof(req.get("action")) != TYPE_DICTIONARY:
		return false
	var action: Dictionary = req["action"]
	if action.size() != 8:
		return false
	for key in ["schema", "world_instance_id", "epoch", "expected_revision",
			"observation_id", "operation_id", "action_type", "arguments"]:
		if not action.has(key):
			return false
	var kind = action["action_type"]
	if _egocentric and kind in ["world.turn", "world.step"]:
		if action["schema"] != VIEW_ACTION_SCHEMA:
			return false
	elif action["schema"] != ACTION_SCHEMA:
		return false
	if not _valid_ref(action["operation_id"]):
		return false
	if typeof(action["world_instance_id"]) != TYPE_STRING or not _valid_uint(action["epoch"]) or not _valid_uint(action["expected_revision"]):
		return false
	if typeof(action["observation_id"]) != TYPE_STRING:
		return false
	if typeof(action["arguments"]) != TYPE_DICTIONARY:
		return false
	var args: Dictionary = action["arguments"]
	if kind == "world.turn":
		return _egocentric and args.size() == 1 and args.get("direction") in ["left", "right"]
	if kind == "world.step":
		return _egocentric and args.size() == 1 and args.get("direction") == "forward"
	if kind == "world.move":
		return not _egocentric and args.size() == 1 and typeof(args.get("direction")) == TYPE_STRING and args["direction"] in ["N", "S", "E", "W"]
	if action["action_type"] in ["world.pick", "world.drop"]:
		return args.size() == 1 and _valid_ref(args.get("item_ref")) and args["item_ref"] == "lab.item.crate"
	return false


# Canonical identity: explicit ordered scalar tuple, independent of JSON key order.
# A digest identifies the exact intended action including epoch, revision and sample.
func _action_digest(action: Dictionary) -> String:
	var argument: String = ""
	if action["action_type"] in ["world.move", "world.turn", "world.step"]:
		argument = action["arguments"]["direction"]
	else:
		argument = action["arguments"]["item_ref"]
	return JSON.stringify([
		action["schema"], action["world_instance_id"], int(action["epoch"]),
		int(action["expected_revision"]), action["observation_id"],
		action["operation_id"], action["action_type"], argument,
	]).sha256_text()


func _operation_status(req: Dictionary, request_id: int) -> Dictionary:
	# Lookup is bound to the FULL intended action, not just a claimed operation ID.
	# Otherwise a caller could attach an existing receipt to different arguments.
	if req.size() != 8 or not _valid_ref(req.get("operation_id")):
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	if typeof(req.get("world_instance_id")) != TYPE_STRING or not _valid_uint(req.get("epoch")):
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	var world_id: String = req["world_instance_id"]
	var matcher := RegEx.create_from_string("^[a-f0-9]{32}$")
	if matcher.search(world_id) == null or int(req["epoch"]) < 1:
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	var requested_action = req.get("action")
	if typeof(requested_action) != TYPE_DICTIONARY:
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	if not _valid_e13_action({
		"protocol": PROTOCOL, "id": request_id, "role": "agent",
		"op": "act", "action": requested_action,
	}):
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	var action: Dictionary = requested_action
	var operation_id: String = req["operation_id"]
	if action["world_instance_id"] != world_id or int(action["epoch"]) != int(req["epoch"]) or action["operation_id"] != operation_id:
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	var data := {
		"schema": OPERATION_STATUS_SCHEMA,
		"world_instance_id": world_id, "epoch": int(req["epoch"]),
		"operation_id": operation_id, "status": "UNKNOWN", "receipt": null,
	}
	# UNKNOWN means absent from *this living ledger*; it never proves no effect.
	if world_id == _world_instance_id and int(req["epoch"]) == _epoch and _operation_ledger.has(operation_id):
		var saved: Dictionary = _operation_ledger[operation_id]
		if saved["digest"] != _action_digest(action):
			return _reply(request_id, false, {}, "OPERATION_CONFLICT")
		data["status"] = "RECORDED"
		data["receipt"] = saved["receipt"].duplicate(true)
	return _reply(request_id, true, data)


func _act(req: Dictionary, request_id: int) -> Dictionary:
	if not _valid_e13_action(req):
		return _reply(request_id, false, {}, "INVALID_ACTION")
	var action: Dictionary = req["action"]
	if action["world_instance_id"] != _world_instance_id:
		return _reply(request_id, false, {}, "WORLD_CHANGED")
	if int(action["epoch"]) != _epoch:
		return _reply(request_id, false, {}, "EPOCH_CHANGED")
	var operation_id: String = action["operation_id"]
	var digest := ""
	if _ledger_enabled:
		digest = _action_digest(action)
		if _operation_ledger.has(operation_id):
			var saved: Dictionary = _operation_ledger[operation_id]
			if digest != saved["digest"]:
				return _reply(request_id, false, {}, "OPERATION_CONFLICT")
			# No tick, revision, event or state mutation on replay.
			var replayed: Dictionary = saved["receipt"].duplicate(true)
			replayed["replayed"] = true
			return _reply(request_id, true, replayed)
		if _operation_ledger.size() >= MAX_E14_LEDGER_ENTRIES:
			return _reply(request_id, false, {}, "OPERATION_CAPACITY")
	else:
		# E1.3 behavior frozen: reject duplicates, do not silently start replaying.
		if _used_operations.has(operation_id):
			return _reply(request_id, false, {}, "OPERATION_REUSED")
		if _used_operations.size() >= MAX_E13_OPERATIONS:
			return _reply(request_id, false, {}, "OPERATION_CAPACITY")
	if int(action["expected_revision"]) != _revision:
		return _reply(request_id, false, {}, "STALE_REVISION")
	if _last_sample.is_empty() or action["observation_id"] != _last_sample.get("sample_id"):
		return _reply(request_id, false, {}, "STALE_SAMPLE")
	if int(action["expected_revision"]) != int(_last_sample.get("revision", -1)):
		return _reply(request_id, false, {}, "STALE_SAMPLE")
	if not _ledger_enabled:
		_used_operations[operation_id] = true
	var kind: String = action["action_type"]
	var args: Dictionary = action["arguments"]
	var applied := false
	var reason := "blocked"
	if kind == "world.turn":
		if args["direction"] == "left":
			_facing = Vector2i(_facing.y, -_facing.x)
		else:
			_facing = Vector2i(-_facing.y, _facing.x)
		applied = true
	elif kind == "world.step":
		var destination := _anima + _facing
		if _inside(destination) and not _blocked(destination):
			_anima = destination
			if _item_owner == "lab.actor.anima":
				_item = destination
			applied = true
		else:
			reason = "occupied"
	elif kind == "world.move":
		var delta := Vector2i.ZERO
		match args["direction"]:
			"N":
				delta = Vector2i(0, -1)
			"S":
				delta = Vector2i(0, 1)
			"E":
				delta = Vector2i(1, 0)
			"W":
				delta = Vector2i(-1, 0)
		var destination := _anima + delta
		if _inside(destination) and not _blocked(destination):
			_anima = destination
			if _item_owner == "lab.actor.anima":
				_item = destination
			applied = true
		else:
			reason = "occupied"
	elif kind == "world.pick":
		if _item_owner != "":
			reason = "already_carried"
		elif absi(_item.x - _anima.x) + absi(_item.y - _anima.y) > 1:
			reason = "not_adjacent"
		else:
			_item_owner = "lab.actor.anima"
			_item = _anima
			applied = true
	elif kind == "world.drop":
		if _item_owner != "lab.actor.anima":
			reason = "not_carrying"
		else:
			_item_owner = ""
			_item = _anima
			applied = true
	if applied:
		_revision += 1
		reason = "ok"
	_tick += 1
	_record("agent", "world_action", {
		"operation_id": operation_id, "action_type": kind,
		"status": "APPLIED" if applied else "BLOCKED", "reason": reason
	})
	queue_redraw()
	_refresh_status()
	var receipt := {
		"schema": RECEIPT_SCHEMA, "world_instance_id": _world_instance_id,
		"epoch": _epoch, "operation_id": operation_id,
		"status": "APPLIED" if applied else "BLOCKED",
		"effect_applied": applied, "reason": reason,
		"revision": _revision, "tick": _tick,
		"event_id": "lifecycle_evt:%d" % _event_seq, "replayed": false,
	}
	if _ledger_enabled:
		_operation_ledger[operation_id] = {"digest": digest, "receipt": receipt.duplicate(true)}
	return _reply(request_id, true, receipt)


# Only operator can obtain designer truth; never included in agent responses.
func _inspect() -> Dictionary:
	var walls: Array[Dictionary] = []
	var obstacles: Array[Dictionary] = []
	for p in _walls:
		walls.append(_cell(p))
	for p in _obstacles:
		obstacles.append(_cell(p))
	return {
		"world_version": WORLD_VERSION, "seed": _seed,
		"world_instance_id": _world_instance_id, "epoch": _epoch,
		"revision": _revision, "tick": _tick,
		"actor": _cell(_anima), "item": _cell(_item), "item_owner": _item_owner,
		"delivery": _cell(_delivery), "landmark": _cell(_landmark),
		"shortcut_blocker": _cell(_shortcut),
		"walls": walls, "obstacles": obstacles,
	}


func _valid_uint(value: Variant) -> bool:
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		return false
	var number := float(value)
	return number >= 0.0 and number <= 2147483647.0 and floor(number) == number


func _reply(request_id: int, ok: bool, data: Dictionary = {}, error: String = "") -> Dictionary:
	var response := {
		"protocol": PROTOCOL, "id": request_id, "ok": ok,
		"epoch": _epoch, "revision": _revision, "tick": _tick,
		"event_seq": _event_seq,
	}
	if ok:
		response["data"] = data
	else:
		response["error"] = error
	return response


func _set_obstacle(req: Dictionary, request_id: int) -> Dictionary:
	if req.size() != 6 or typeof(req.get("at")) != TYPE_DICTIONARY or typeof(req.get("blocked")) != TYPE_BOOL:
		return _reply(request_id, false, {}, "INVALID_FIXTURE")
	var raw: Dictionary = req["at"]
	if raw.size() != 2 or not raw.has("x") or not raw.has("y") or not _valid_uint(raw["x"]) or not _valid_uint(raw["y"]):
		return _reply(request_id, false, {}, "INVALID_CELL")
	var position := Vector2i(int(raw["x"]), int(raw["y"]))
	if not _inside(position) or position in _walls or position == _shortcut or position == _anima or position == _item or position == _delivery or position == _landmark:
		return _reply(request_id, false, {}, "INVALID_CELL")
	if position.x == int(_scenario["partition"]["x"]):
		return _reply(request_id, false, {}, "RESERVED_GATE")
	var present := position in _obstacles
	if bool(req["blocked"]) and not present and _obstacles.size() >= MAX_DYNAMIC_OBSTACLES:
		return _reply(request_id, false, {}, "OBSTACLE_CAPACITY")
	var changed: bool = present != bool(req["blocked"])
	if changed:
		if bool(req["blocked"]):
			_obstacles.append(position)
		else:
			_obstacles.erase(position)
		_revision += 1
		_tick += 1
	_record("harness", "set_obstacle", {
		"cell": _cell(position), "blocked": req["blocked"], "changed": changed
	})
	queue_redraw()
	_refresh_status()
	return _reply(request_id, true, {"cell": _cell(position), "blocked": req["blocked"], "changed": changed})



# E2.5c: strictly operator-only intervention to create contradictory history.
# No global target coordinates are returned to observer/executor or included in
# the runner's agent Context. The test harness may separately inspect truth.
func _relocate_item(req: Dictionary, request_id: int) -> Dictionary:
	if req.size() != 10:
		return _reply(request_id, false, {}, "INVALID_FIXTURE")
	var fixture_id = req.get("fixture_id")
	var key_pattern := RegEx.create_from_string("^[A-Za-z][A-Za-z0-9_-]{0,63}$")
	if typeof(fixture_id) != TYPE_STRING or key_pattern.search(fixture_id) == null:
		return _reply(request_id, false, {}, "INVALID_FIXTURE")
	if typeof(req.get("world_instance_id")) != TYPE_STRING or not _valid_uint(req.get("epoch")):
		return _reply(request_id, false, {}, "INVALID_FIXTURE")
	if req["world_instance_id"] != _world_instance_id or int(req["epoch"]) != _epoch:
		return _reply(request_id, false, {}, "WORLD_CHANGED")
	if not _valid_uint(req.get("expected_revision")) or typeof(req.get("expected_sample_id")) != TYPE_STRING:
		return _reply(request_id, false, {}, "INVALID_FIXTURE")
	var at = req.get("at")
	if typeof(at) != TYPE_DICTIONARY:
		return _reply(request_id, false, {}, "INVALID_CELL")
	var raw: Dictionary = at
	if raw.size() != 2 or not raw.has("x") or not raw.has("y") or not _valid_uint(raw["x"]) or not _valid_uint(raw["y"]):
		return _reply(request_id, false, {}, "INVALID_CELL")
	var destination := Vector2i(int(raw["x"]), int(raw["y"]))
	if (not _inside(destination) or _blocked(destination) or destination == _anima
			or destination == _delivery or destination == _landmark or _item_owner != ""):
		return _reply(request_id, false, {}, "INVALID_CELL")
	var digest := JSON.stringify([fixture_id, req["world_instance_id"], int(req["epoch"]),
		int(req["expected_revision"]), req["expected_sample_id"], destination.x, destination.y]).sha256_text()
	if _fixture_ledger.has(fixture_id):
		var saved: Dictionary = _fixture_ledger[fixture_id]
		if digest != saved["digest"]:
			return _reply(request_id, false, {}, "FIXTURE_CONFLICT")
		var replay: Dictionary = saved["receipt"].duplicate(true)
		replay["replayed"] = true
		return _reply(request_id, true, replay)
	if destination == _item:
		return _reply(request_id, false, {}, "INVALID_CELL")
	if int(req["expected_revision"]) != _revision:
		return _reply(request_id, false, {}, "STALE_REVISION")
	if (_last_sample.is_empty() or req["expected_sample_id"] != _last_sample.get("sample_id")
			or int(_last_sample.get("revision", -1)) != _revision):
		return _reply(request_id, false, {}, "STALE_SAMPLE")
	_item = destination
	_revision += 1
	_tick += 1
	_record("operator_fixture", "relocate_item", {"fixture_id": fixture_id, "changed": true})
	queue_redraw()
	_refresh_status()
	var receipt := {
		"schema": E25C_FIXTURE_RECEIPT,
		"fixture_id": fixture_id, "world_instance_id": _world_instance_id,
		"epoch": _epoch, "before_sample_id": req["expected_sample_id"],
		"kind": "item_relocated", "status": "APPLIED",
		"revision": _revision, "tick": _tick,
		"event_id": "lifecycle_evt:%d" % _event_seq, "replayed": false,
	}
	_fixture_ledger[fixture_id] = {"digest": digest, "receipt": receipt.duplicate(true)}
	return _reply(request_id, true, receipt)


func _request(line: String) -> Dictionary:
	var req = JSON.parse_string(line)
	if typeof(req) != TYPE_DICTIONARY:
		return _reply(0, false, {}, "MALFORMED_JSON")
	if not _valid_uint(req.get("id")):
		return _reply(0, false, {}, "INVALID_ID")
	var request_id: int = int(req["id"])
	if req.get("protocol") != PROTOCOL:
		return _reply(request_id, false, {}, "UNSUPPORTED_PROTOCOL")
	var role = req.get("role")
	var op = req.get("op")
	if typeof(role) != TYPE_STRING or not role in ["agent", "operator"] or typeof(op) != TYPE_STRING:
		return _reply(request_id, false, {}, "INVALID_ROLE_OR_OPERATION")
	var authority := ""
	if _guarded:
		# Verify BEFORE performing any operation or constructing hello/inspect.
		# Remove bearer field from the request forwarded to strict DTO validators
		# and never include it in event history, hello, receipt or error.
		var submitted = req.get("auth")
		if typeof(submitted) != TYPE_STRING:
			return _reply(request_id, false, {}, "UNAUTHORIZED")
		if role == "operator" and submitted == _operator_key:
			authority = "operator"
		elif role == "agent" and submitted == _observer_key:
			authority = "observer"
		elif role == "agent" and submitted == _executor_key:
			authority = "executor"
		else:
			return _reply(request_id, false, {}, "UNAUTHORIZED")
		req.erase("auth")
	if op == "hello" and req.size() == 4:
		# The observer sees only observe, even if this world has effects.
		var caps: Array[String] = ["observe"]
		if _egocentric:
			caps.clear()
			caps.append("observe_view")
		if _guarded:
			if authority == "operator":
				caps = ["inspect", "reset", "set_obstacle"]
				if _e25c_fixtures:
					caps.append("relocate_item")
			elif authority == "executor":
				caps = []
				if _effects_enabled:
					caps.append("act")
				if _ledger_enabled:
					caps.append("operation_status")
		else:
			if _effects_enabled:
				caps.append("act")
			if _ledger_enabled:
				caps.append("operation_status")
		var greeting := {
			"ready": true, "world_version": WORLD_VERSION,
			"world_instance_id": _world_instance_id, "epoch": _epoch,
			"capabilities": caps,
		}
		if _guarded:
			greeting["auth_mode"] = "guarded"
		if role == "operator":
			greeting["seed"] = _seed
		return _reply(request_id, true, greeting)
	if role == "agent":
		if op == "observe_view" and _egocentric and req.size() == 4 and authority == "observer":
			return _reply(request_id, true, _observation_view())
		if op == "observe" and not _egocentric and req.size() == 4 and (not _guarded or authority == "observer"):
			return _reply(request_id, true, _observation())
		if op == "act" and _effects_enabled and (not _guarded or authority == "executor"):
			return _act(req, request_id)
		if op == "operation_status" and _ledger_enabled and (not _guarded or authority == "executor"):
			return _operation_status(req, request_id)
		return _reply(request_id, false, {}, "FORBIDDEN")
	if op == "act":
		return _reply(request_id, false, {}, "FORBIDDEN")
	if op == "inspect" and req.size() == 4:
		return _reply(request_id, true, _inspect())
	if op == "reset" and req.size() == 4:
		_reset_world()
		return _reply(request_id, true, {
			"world_instance_id": _world_instance_id, "epoch": _epoch,
			"revision": _revision,
		})
	if op == "set_obstacle":
		return _set_obstacle(req, request_id)
	if op == "relocate_item" and _guarded and authority == "operator" and _e25c_fixtures:
		return _relocate_item(req, request_id)
	return _reply(request_id, false, {}, "UNKNOWN_OPERATION")


func _process(_delta: float) -> void:
	if _peer == null:
		if _server.is_connection_available():
			_peer = _server.take_connection()
			_buffer = ""
		return
	_peer.poll()
	if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		_peer = null
		_buffer = ""
		return
	var available := _peer.get_available_bytes()
	if available > 0:
		var read_count: int = mini(available, MAX_LINE_BYTES)
		var reply: Array = _peer.get_data(read_count)
		if reply[0] != OK:
			_peer.disconnect_from_host()
			_peer = null
			return
		var bytes: PackedByteArray = reply[1]
		_buffer += bytes.get_string_from_utf8()
	if _buffer.to_utf8_buffer().size() > MAX_LINE_BYTES:
		_peer.disconnect_from_host()
		_peer = null
		_buffer = ""
		return
	var processed := 0
	while _buffer.contains("\n") and processed < 8:
		var cut := _buffer.find("\n")
		var line := _buffer.substr(0, cut)
		_buffer = _buffer.substr(cut + 1)
		var response := _request(line)
		_peer.put_data((JSON.stringify(response) + "\n").to_utf8_buffer())
		processed += 1



# E2.x human-facing debug UI, deliberately NOT a source of ANIMA knowledge.
# This pane is operator truth + presentation-only previews. Sensor and cognition
# values below are populated ONLY from real captured samples / authenticated
# external telemetry; never fabricate a "thinking" Core from world truth.
func _build_debug_panel() -> void:
	var side := ColorRect.new()
	side.position = Vector2(WIDTH * CELL + 6, 4)
	side.size = Vector2(282, HEIGHT * CELL - 8)
	side.color = Color(0.09, 0.12, 0.16, 1.0)
	add_child(side)
	var scroll := ScrollContainer.new()
	scroll.position = Vector2(WIDTH * CELL + 15, 11)
	scroll.size = Vector2(263, HEIGHT * CELL - 20)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	_debug_panel = Label.new()
	_debug_panel.custom_minimum_size = Vector2(251, 0)
	_debug_panel.add_theme_font_size_override("font_size", 12)
	_debug_panel.add_theme_color_override("font_color", Color(0.89, 0.93, 0.97))
	_debug_panel.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	scroll.add_child(_debug_panel)
	_refresh_debug_panel()


func _facing_word() -> String:
	if _facing == Vector2i(0, -1):
		return "N"
	if _facing == Vector2i(1, 0):
		return "E"
	if _facing == Vector2i(0, 1):
		return "S"
	return "W"


func _friendly_entity(ref: String) -> String:
	if ref.begins_with("lab.item."):
		return "crate / item"
	if ref.begins_with("lab.zone."):
		return "delivery / zone"
	if ref.begins_with("lab.landmark."):
		return "landmark"
	if ref.begins_with("lab.obstacle."):
		return "obstacle"
	if ref.begins_with("lab.surface.") or ref.begins_with("lab.wall."):
		return "wall / surface"
	return "other entity"


# E2.5b telemetry only from authenticated Python runner. World truth above
# stays operator-only, is never serialized to the runner or agent.
func _visual_runner_update(state: Dictionary) -> void:
	_visual_state = state.duplicate(true)
	_visual_error = ""
	_refresh_debug_panel()


func _visual_runner_error(message: String) -> void:
	_visual_state.clear()
	_visual_error = message
	_refresh_debug_panel()


func _refresh_debug_panel() -> void:
	if _debug_panel == null:
		return
	var mode := "E2.3 VIEW CONE 90deg" if _egocentric else "E1.2 RANGE 3 (360deg)"
	var lines: Array[String] = [
		"VISUAL ANIMA LAB  /  DEBUG",
		"OPERATOR PANEL - NOT AGENT INPUT",
		"--------------------------------",
		"WORLD TRUTH  (operator only)",
		"seed=%d  epoch=%d  revision=%d" % [_seed, _epoch, _revision],
		"tick=%d  actions=%d" % [_tick, _event_seq],
		"ANIMA cell: (%d, %d)  facing: %s" % [_anima.x, _anima.y, _facing_word()],
		"crate cell: (%d, %d)" % [_item.x, _item.y],
		"owner: %s" % ["none" if _item_owner == "" else "ANIMA"],
		"",
		"MAP LEGEND",
		"green: ANIMA   yellow: crate",
		"blue: delivery   purple: marker",
		"red: blocker   ochre: obstacle",
		"gray: walls   cyan: sensor preview",
		"",
		"AGENT SENSOR  (recorded only)",
		mode,
	]
	if _last_sample.is_empty():
		lines.append("No observation requested yet.")
	else:
		var data: Dictionary = _last_sample
		var readings: Array = data.get("readings", [])
		lines.append("sample=%d  visible records=%d" % [int(data.get("sample_seq", -1)), readings.size()])
		var shown := 0
		for reading in readings:
			if shown >= 5:
				break
			if typeof(reading) != TYPE_DICTIONARY:
				continue
			var ref := String(reading.get("entity_ref", reading.get("subject_ref", "")))
			lines.append("- " + _friendly_entity(ref))
			shown += 1
		if readings.size() > shown:
			lines.append("... +%d more readings" % [readings.size() - shown])
	lines.append("")
	lines.append("CORE / MEMORY / COGNITION")
	if _visual_control_port == 0:
		lines.append("Telemetry: NOT CONNECTED")
		lines.append("Decision trace: UNAVAILABLE")
		lines.append("FAST/DEEP: NOT CONNECTED")
	elif _visual_state.is_empty():
		lines.append("Telemetry: " + _visual_error)
	else:
		lines.append("Source: CORE-BACKED RAW")
		lines.append("Goal: " + String(_visual_state.get("goal", "?")))
		lines.append("Status: " + String(_visual_state.get("goal_status", "?")))
		lines.append("Mode: DETERMINISTIC / FAST OFF")
		lines.append("Step: %d / %d" % [
			int(_visual_state.get("steps", 0)), int(_visual_state.get("max_steps", 0))])
		lines.append("Trial: " + String(_visual_state.get("scenario", "baseline")))
		lines.append("Memory: " + ("ON" if _visual_state.get("memory_enabled") else "OFF"))
		lines.append("Admission: " + String(_visual_state.get(
			"action_admission", "UNKNOWN"
		)))
		if _visual_state.get("core_goal_id") != null:
			lines.append("Core Goal: " + String(_visual_state.get("core_goal_status", "?")))
		lines.append("Agent view (real Core Raw):")
		var current: Array = _visual_state.get("agent_view", [])
		if current.is_empty():
			lines.append("  No target/obstacle visible")
		for item in current:
			lines.append("  " + _friendly_entity(String(item.get("entity_ref", "")))
				+ "  %dmdeg / %dmcell" % [
					int(item.get("bearing_mdeg", 0)), int(item.get("range_milli_cells", 0))])
		lines.append("Working Memory (Core-backed):")
		var remembered: Array = _visual_state.get("memory", [])
		if remembered.is_empty():
			lines.append("  No recalled target")
		for entry in remembered:
			lines.append("  " + _friendly_entity(String(entry.get("entity_ref", "")))
				+ ": " + String(entry.get("status", "?")))
		var last_choice: Variant = _visual_state.get("last_choice")
		if typeof(last_choice) == TYPE_DICTIONARY:
			lines.append("Decision: %s(%s)" % [
				String(last_choice.get("operation", "?")),
				String(last_choice.get("direction", "?"))
			])
			lines.append("Reason: " + String(last_choice.get("reason_code", "?")))
		lines.append("MEMORY HYPOTHESES (not Knowledge)")
		var hypotheses: Array = _visual_state.get("hypotheses", [])
		if hypotheses.is_empty():
			lines.append("  No conflict detected")
		for hypothesis in hypotheses:
			if typeof(hypothesis) != TYPE_DICTIONARY:
				continue
			lines.append("  " + String(hypothesis.get("status", "?")))
			lines.append("  old: " + String(hypothesis.get("prior_event_id", "?")))
			lines.append("  check: " + String(hypothesis.get("suspected_event_id", "?")))
		lines.append("")
		var last_outcome: Variant = _visual_state.get("last_outcome")
		if typeof(last_outcome) == TYPE_DICTIONARY:
			lines.append("Verification: " + String(last_outcome.get("status", "?")))
		lines.append("DECISION TRACE (verified/lab)")
		var trace: Array = _visual_state.get("trace", [])
		for event in trace:
			lines.append("  " + String(event.get("stage", "?"))
				+ ": " + String(event.get("text", "?")))
		if _visual_state.get("error") != null:
			lines.append("ERROR: " + String(_visual_state.get("error")))
	lines.append("")
	lines.append("RECENT WORLD EVENTS")
	for i in range(maxi(0, _history.size() - 3), _history.size()):
		var event: Dictionary = _history[i]
		lines.append("#%d %s: %s" % [
			int(event.get("event_seq", -1)), String(event.get("actor", "?")),
			String(event.get("event", "?"))
		])
	var display_text := ""
	for line in lines:
		display_text += line + "\n"
	_debug_panel.text = display_text


func _refresh_status() -> void:
	if _status != null:
		if _guarded:
			_status.text = "ANIMA / E2.1 GUARDED LAB | epoch=%d revision=%d\nNo Core action authority" % [_epoch, _revision]
		else:
			var mode := "E1.3 TEST EFFECTS" if _effects_enabled else "E1.2 OBSERVE-ONLY"
			_status.text = "ANIMA / %s  |  seed=%d  epoch=%d  revision=%d\nLaboratory-only; no Core authority" % [mode, _seed, _epoch, _revision]
	_refresh_debug_panel()


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, Vector2(WIDTH * CELL, HEIGHT * CELL)), Color(0.10, 0.13, 0.17), true)
	for x in range(WIDTH):
		for y in range(HEIGHT):
			var p := Vector2i(x, y)
			var color := Color(0.17, 0.22, 0.27)
			if p in _walls:
				color = Color(0.35, 0.40, 0.46)
			elif p == _shortcut:
				color = Color(0.66, 0.20, 0.18)
			elif p in _obstacles:
				color = Color(0.61, 0.45, 0.18)
			draw_rect(Rect2(Vector2(x * CELL + 1, y * CELL + 1), Vector2(CELL - 2, CELL - 2)), color, true)
	# Visual-only diagnostic coverage. It is NOT a recorded sensor event and
	# must never be passed to the observer, Core, Memory, FAST or DEEP.
	if _debug_ui_enabled:
		for x in range(1, WIDTH - 1):
			for y in range(1, HEIGHT - 1):
				var point := Vector2i(x, y)
				if point == _anima or _blocked(point):
					continue
				var exposed := _view_visible(point) if _egocentric else _visible(point)
				if exposed:
					draw_rect(
						Rect2(Vector2(x * CELL + 3, y * CELL + 3), Vector2(CELL - 6, CELL - 6)),
						Color(0.10, 0.78, 0.85, 0.17), true
					)
	for item in [
		{"at": _delivery, "color": Color(0.20, 0.62, 0.72)},
		{"at": _landmark, "color": Color(0.67, 0.46, 0.80)},
		{"at": _item, "color": Color(0.97, 0.78, 0.28)},
		{"at": _anima, "color": Color(0.20, 0.85, 0.40)},
	]:
		var at: Vector2i = item["at"]
		draw_circle(Vector2(float(at.x * CELL + CELL / 2), float(at.y * CELL + CELL / 2)), float(CELL) * 0.30, item["color"])
	if _debug_ui_enabled:
		var center := Vector2(float(_anima.x * CELL + CELL / 2), float(_anima.y * CELL + CELL / 2))
		var ahead := center + Vector2(float(_facing.x), float(_facing.y)) * float(CELL) * 0.43
		draw_line(center, ahead, Color(1.0, 1.0, 1.0, 0.95), 3.0)
		draw_circle(ahead, 3.5, Color(1.0, 1.0, 1.0, 0.95))
