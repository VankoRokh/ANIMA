extends Node2D
## Isolated lifecycle world; NEVER replaces the P5/P6 Main scene.
## Default: E1.2 observe-only; E1.3 world effects require explicit --lifecycle-effects.
## Self-declared bridge roles are laboratory-only, not trusted authentication or Core authority.

const PROTOCOL := "val.bridge/0.2"
const OBSERVATION_SCHEMA := "anima.lifecycle.world_observation/0.1"
const ACTION_SCHEMA := "anima.lifecycle.world_action/0.1"
const RECEIPT_SCHEMA := "anima.lifecycle.world_receipt/0.1"
const OPERATION_STATUS_SCHEMA := "anima.lifecycle.world_operation_status/0.1"
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
var _item := Vector2i.ZERO
var _delivery := Vector2i.ZERO
var _landmark := Vector2i.ZERO
var _scenario: Dictionary = {}
var _history: Array[Dictionary] = []
var _last_sample: Dictionary = {}
var _status: Label = null


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_parse_args()
	_reset_world()
	_status = Label.new()
	_status.position = Vector2(14, HEIGHT * CELL + 12)
	_status.add_theme_font_size_override("font_size", 16)
	add_child(_status)
	_refresh_status()
	var listen_error := _server.listen(_port, "127.0.0.1")
	if listen_error != OK:
		push_error("Lifecycle World: cannot bind loopback port %d" % _port)
		get_tree().quit(2)
		return
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
		index += 1
	if _ledger_enabled and not _effects_enabled:
		push_error("Lifecycle World: ledger requires --lifecycle-effects")
		get_tree().quit(2)
		return
	if _port < 1024 or _port > 65535 or _seed < 0 or _seed > 2147483647:
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
	_revision = 0
	_tick = 0
	_last_sample.clear()
	_history.clear()
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
	if action["schema"] != ACTION_SCHEMA or not _valid_ref(action["operation_id"]):
		return false
	if typeof(action["world_instance_id"]) != TYPE_STRING or not _valid_uint(action["epoch"]) or not _valid_uint(action["expected_revision"]):
		return false
	if typeof(action["observation_id"]) != TYPE_STRING:
		return false
	if typeof(action["arguments"]) != TYPE_DICTIONARY:
		return false
	var args: Dictionary = action["arguments"]
	if action["action_type"] == "world.move":
		return args.size() == 1 and typeof(args.get("direction")) == TYPE_STRING and args["direction"] in ["N", "S", "E", "W"]
	if action["action_type"] in ["world.pick", "world.drop"]:
		return args.size() == 1 and _valid_ref(args.get("item_ref")) and args["item_ref"] == "lab.item.crate"
	return false


# Canonical identity: explicit ordered scalar tuple, independent of JSON key order.
# A digest identifies the exact intended action including epoch, revision and sample.
func _action_digest(action: Dictionary) -> String:
	var argument: String = ""
	if action["action_type"] == "world.move":
		argument = action["arguments"]["direction"]
	else:
		argument = action["arguments"]["item_ref"]
	return JSON.stringify([
		action["schema"], action["world_instance_id"], int(action["epoch"]),
		int(action["expected_revision"]), action["observation_id"],
		action["operation_id"], action["action_type"], argument,
	]).sha256_text()


func _operation_status(req: Dictionary, request_id: int) -> Dictionary:
	if req.size() != 7 or not _valid_ref(req.get("operation_id")):
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	if typeof(req.get("world_instance_id")) != TYPE_STRING or not _valid_uint(req.get("epoch")):
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	var world_id: String = req["world_instance_id"]
	var matcher := RegEx.create_from_string("^[a-f0-9]{32}$")
	if matcher.search(world_id) == null or int(req["epoch"]) < 1:
		return _reply(request_id, false, {}, "INVALID_LOOKUP")
	var operation_id: String = req["operation_id"]
	var data := {
		"schema": OPERATION_STATUS_SCHEMA,
		"world_instance_id": world_id, "epoch": int(req["epoch"]),
		"operation_id": operation_id, "status": "UNKNOWN", "receipt": null,
	}
	# UNKNOWN means absent from *this living ledger*; it never proves no effect.
	if world_id == _world_instance_id and int(req["epoch"]) == _epoch and _operation_ledger.has(operation_id):
		data["status"] = "RECORDED"
		data["receipt"] = _operation_ledger[operation_id]["receipt"].duplicate(true)
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
	if _ledger_enabled:
		var digest: String = _action_digest(action)
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
	if kind == "world.move":
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
	if op == "hello" and req.size() == 4:
		# The agent does not receive the seed or designer truth.
		var caps: Array[String] = ["observe"]
		if _effects_enabled:
			caps.append("act")
		if _ledger_enabled:
			caps.append("operation_status")
		var greeting := {
			"ready": true, "world_version": WORLD_VERSION,
			"world_instance_id": _world_instance_id, "epoch": _epoch,
			"capabilities": caps,
		}
		if role == "operator":
			greeting["seed"] = _seed
		return _reply(request_id, true, greeting)
	if role == "agent":
		if op == "observe" and req.size() == 4:
			return _reply(request_id, true, _observation())
		if op == "act" and _effects_enabled:
			return _act(req, request_id)
		if op == "operation_status" and _ledger_enabled:
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


func _refresh_status() -> void:
	if _status != null:
		var mode := "E1.3 TEST EFFECTS" if _effects_enabled else "E1.2 OBSERVE-ONLY"
		_status.text = "ANIMA / %s  |  seed=%d  epoch=%d  revision=%d\nLaboratory-only; no Core authority" % [mode, _seed, _epoch, _revision]


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
	for item in [
		{"at": _delivery, "color": Color(0.20, 0.62, 0.72)},
		{"at": _landmark, "color": Color(0.67, 0.46, 0.80)},
		{"at": _item, "color": Color(0.97, 0.78, 0.28)},
		{"at": _anima, "color": Color(0.20, 0.85, 0.40)},
	]:
		var at: Vector2i = item["at"]
		draw_circle(Vector2(float(at.x * CELL + CELL / 2), float(at.y * CELL + CELL / 2)), float(CELL) * 0.30, item["color"])
