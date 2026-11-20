extends Node2D
## E1.2 isolated lifecycle world. Not the P5/P6 Main scene.
## Truth belongs to Godot; the agent bridge exposes local observations ONLY.
## World effects and Core authority are deliberately deferred to E1.3/E2.

const PROTOCOL := "val.bridge/0.2"
const OBSERVATION_SCHEMA := "anima.lifecycle.world_observation/0.1"
const WORLD_VERSION := "lifecycle-grid/0.1"
const WIDTH := 14
const HEIGHT := 11
const CELL := 48
const SENSE_RADIUS := 3
const MAX_LINE_BYTES := 8192
const MAX_DYNAMIC_OBSTACLES := 8

var _server: TCPServer = TCPServer.new()
var _peer: StreamPeerTCP = null
var _buffer := ""
var _port := 46029
var _seed := 7
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
		index += 1
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
	_revision = 0
	_tick = 0
	_last_sample.clear()
	_history.clear()
	_walls.clear()
	_obstacles.clear()
	var partition: Dictionary = _scenario["partition"]
	var gaps: Array = partition["open_y"]
	for x in range(WIDTH):
		_walls.append(Vector2i(x, 0))
		_walls.append(Vector2i(x, HEIGHT - 1))
	for y in range(1, HEIGHT - 1):
		_walls.append(Vector2i(0, y))
		_walls.append(Vector2i(WIDTH - 1, y))
		if not y in gaps:
			_walls.append(Vector2i(int(partition["x"]), y))
	_shortcut = _point(_scenario["shortcut_blocker"])
	var choices: Array = _scenario["seeded_obstacles"]
	_obstacles.append(_point(choices[_seed % choices.size()]))
	_anima = _point(_scenario["actor_start"])
	_item = _point(_scenario["item"]["at"])
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
		readings.append(_reading("lab.item.crate", "owner", "absent", null, _item))
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
		"actor": _cell(_anima), "item": _cell(_item),
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
		var greeting := {
			"ready": true, "world_version": WORLD_VERSION,
			"world_instance_id": _world_instance_id, "epoch": _epoch,
			"capabilities": ["observe"],
		}
		if role == "operator":
			greeting["seed"] = _seed
		return _reply(request_id, true, greeting)
	if role == "agent":
		if op == "observe" and req.size() == 4:
			return _reply(request_id, true, _observation())
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
		_buffer += (reply[1] as PackedByteArray).get_string_from_utf8()
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
		_status.text = "ANIMA / E1.2  |  seed=%d  epoch=%d  revision=%d\nOBSERVE-ONLY: no agent actions admitted" % [_seed, _epoch, _revision]


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
