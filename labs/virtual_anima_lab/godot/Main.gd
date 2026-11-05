extends Node2D
## P5-A independent world. ANIMA Core is intentionally NOT imported.
## The loopback bridge is a feasibility protocol, not authentication.

const PROTOCOL := "val.bridge/0.1" # Stable P5-A compatibility profile.
const PROTOCOL_V2 := "val.bridge/0.2" # New P5-B typed/conditional profile.
const WORLD_VERSION := "p5a-grid/0.1" # Same geometry; protocol is independently versioned.
const OBSERVATION_VERSION := "val.observation/0.1"
const ACTION_VERSION := "val.action/0.1"
const MAX_ACTION_KEYS := 1024
const WIDTH := 12
const HEIGHT := 8
const CELL := 56
const SENSE_RADIUS := 3
const MAX_LINE_BYTES := 8192
const MAX_EVENTS := 256
const MAX_DYNAMIC_OBSTACLES := 8
const SCENARIOS := ["base", "detour", "clutter"]

var _server: TCPServer = TCPServer.new()
var _peer: StreamPeerTCP = null
var _buffer := ""
var _port := 46019
var _seed := 7
var _scenario := "base"
var _ui_mode := "normal" # Display-only choice; never changes world truth or agent access.
var _tick := 0
var _epoch := 0
var _revision := 0
var _event_seq := 0
var _sample_seq := 0
var _last_sample: Dictionary = {}
var _action_ledger: Dictionary = {}
var _paused := false
var _human := Vector2i(2, 2)
var _anima := Vector2i(9, 5)
var _door := Vector2i(6, 3)
var _door_open := false
var _marker := Vector2i(8, 2)
var _walls: Array[Vector2i] = []
var _dynamic_obstacles: Array[Vector2i] = []
var _history: Array[Dictionary] = []
var _hud: Label
var _diagnostics: Label
var _guide: Label


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_parse_args()
	if not _scenario in SCENARIOS:
		push_error("VAL: unknown lab scenario: %s" % _scenario)
		get_tree().quit(2)
		return
	if not _ui_mode in ["normal", "debug"]:
		push_error("VAL: unknown lab UI mode: %s" % _ui_mode)
		get_tree().quit(2)
		return
	_reset_world()
	_hud = Label.new()
	_hud.position = Vector2(24, 466)
	_hud.add_theme_font_size_override("font_size", 17)
	add_child(_hud)
	_diagnostics = Label.new()
	_diagnostics.position = Vector2(WIDTH * CELL + 16, 22)
	_diagnostics.add_theme_font_size_override("font_size", 15)
	add_child(_diagnostics)
	_guide = Label.new()
	_guide.position = Vector2(WIDTH * CELL + 16, 72)
	_guide.add_theme_font_size_override("font_size", 17)
	_guide.text = "VIRTUAL ANIMA LAB\n\nHuman: WASD / arrows\nDoor: E (when nearby)\n\nANIMA: Python bridge\n\nF3: Developer diagnostics\n\nWorld: local simulation"
	add_child(_guide)
	_set_ui_mode(_ui_mode)
	var listen_error := _server.listen(_port, "127.0.0.1")
	if listen_error != OK:
		push_error("VAL: cannot bind 127.0.0.1:%d (%s)" % [_port, listen_error])
		get_tree().quit(2)
		return
	print("ANIMA_LAB_READY protocol=%s port=%d seed=%d" % [PROTOCOL, _port, _seed])


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		if args[i] == "--lab-port" and i + 1 < args.size():
			_port = int(args[i + 1])
			i += 1
		elif args[i] == "--lab-seed" and i + 1 < args.size():
			_seed = int(args[i + 1])
			i += 1
		elif args[i] == "--lab-scenario" and i + 1 < args.size():
			_scenario = args[i + 1]
			i += 1
		elif args[i] == "--lab-ui" and i + 1 < args.size():
			_ui_mode = args[i + 1]
			i += 1
		i += 1
	if _port < 1024 or _port > 65535 or _seed < 0:
		push_error("VAL: invalid port or seed")
		get_tree().quit(2)
		return


# Local viewport controls only. No world revision, tick, event or authorization change.
func _set_ui_mode(mode: String) -> void:
	if not mode in ["normal", "debug"]:
		return
	_ui_mode = mode
	if _diagnostics != null:
		_diagnostics.visible = mode == "debug"
	if _guide != null:
		_guide.visible = mode == "normal"
	_refresh_hud()


func _reset_world() -> void:
	# Each reset creates a different world incarnation. Tick and revision
	# restart; event/sample sequence numbers NEVER go backwards in a process.
	_epoch += 1
	_revision = 0
	_tick = 0
	_paused = false
	_last_sample.clear()
	_action_ledger.clear()
	_human = Vector2i(2, 2)
	_anima = Vector2i(9, 5)
	_door_open = false
	_walls.clear()
	_dynamic_obstacles.clear()
	_history.clear()
	for x in range(WIDTH):
		_walls.append(Vector2i(x, 0))
		_walls.append(Vector2i(x, HEIGHT - 1))
	for y in range(1, HEIGHT - 1):
		_walls.append(Vector2i(0, y))
		_walls.append(Vector2i(WIDTH - 1, y))
	_walls.append(Vector2i(4, 3))
	_walls.append(Vector2i(4, 4))
	if _scenario == "detour":
		_walls.append(Vector2i(7, 4))
	elif _scenario == "clutter":
		_walls.append(Vector2i(5, 5))
		_walls.append(Vector2i(8, 3))
	var choices: Array[Vector2i] = [
		Vector2i(8, 2), Vector2i(8, 4), Vector2i(3, 5),
	]
	var rng := RandomNumberGenerator.new()
	rng.seed = _seed
	_marker = choices[rng.randi_range(0, choices.size() - 1)]
	_record("lab", "reset", {
		"seed": _seed, "world_version": WORLD_VERSION, "scenario": _scenario,
	})
	queue_redraw()


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
		var payload := (JSON.stringify(response) + "\n").to_utf8_buffer()
		_peer.put_data(payload)
		processed += 1


func _request(line: String) -> Dictionary:
	var req = JSON.parse_string(line)
	if typeof(req) != TYPE_DICTIONARY:
		return _reply(null, false, {}, "MALFORMED_JSON")
	# Godot's JSON parser represents JSON numbers as TYPE_FLOAT, even
	# when Python sends an integer such as {"id": 1}. Validate the numeric
	# contract first and normalize the reply ID to a true Godot int so Python
	# json.loads receives 1, not 1.0.
	var raw_id = req.get("id")
	if typeof(raw_id) != TYPE_INT and typeof(raw_id) != TYPE_FLOAT:
		return _reply(null, false, {}, "INVALID_ID")
	var numeric_id: float = float(raw_id)
	if not (
		numeric_id >= 0.0
		and numeric_id <= 2147483647.0
		and numeric_id == floor(numeric_id)
	):
		return _reply(null, false, {}, "INVALID_ID")
	var request_id: int = int(raw_id)
	if req.get("protocol") == PROTOCOL_V2:
		return _request_v2(req, request_id)
	if req.get("protocol") != PROTOCOL:
		return _reply(request_id, false, {}, "UNSUPPORTED_PROTOCOL")
	var role: String = str(req.get("role", ""))
	var op: String = str(req.get("op", ""))
	if role != "agent" and role != "operator":
		return _reply(request_id, false, {}, "INVALID_ROLE")
	if op == "ping":
		return _reply(request_id, true, {
			"ready": true, "world_version": WORLD_VERSION, "seed": _seed,
		})
	if role == "agent":
		match op:
			"observe":
				return _reply(request_id, true, _agent_observation())
			"move":
				if _paused:
					return _reply(request_id, false, {}, "PAUSED")
				var direction := str(req.get("direction", ""))
				if not direction in ["N", "S", "E", "W"]:
					return _reply(request_id, false, {}, "INVALID_DIRECTION")
				return _reply(request_id, true, _move("anima", direction))
			_:
				return _reply(request_id, false, {}, "FORBIDDEN")
	match op:
		"debug_snapshot":
			return _reply(request_id, true, _debug_snapshot())
		"trace":
			# Keep one JSON response below the bounded 8192-byte frame size.
			var start: int = maxi(0, _history.size() - 20)
			return _reply(
				request_id, true,
				{"events": _history.slice(start, _history.size()).duplicate(true)},
			)
		"human_move":
			if _paused:
				return _reply(request_id, false, {}, "PAUSED")
			var direction := str(req.get("direction", ""))
			if not direction in ["N", "S", "E", "W"]:
				return _reply(request_id, false, {}, "INVALID_DIRECTION")
			return _reply(request_id, true, _move("human", direction))
		"set_door":
			var desired = req.get("open")
			if typeof(desired) != TYPE_BOOL:
				return _reply(request_id, false, {}, "INVALID_DOOR_STATE")
			if not bool(desired) and (_human == _door or _anima == _door):
				return _reply(request_id, false, {}, "DOOR_OCCUPIED")
			_tick += 1
			if _door_open != bool(desired):
				_revision += 1
			_door_open = bool(desired)
			_record("operator", "set_door", {"open": _door_open})
			queue_redraw()
			_refresh_hud()
			return _reply(request_id, true, {"open": _door_open})
		"pause":
			if not _paused:
				_revision += 1
			_paused = true
			_record("operator", "pause", {})
			_refresh_hud()
			return _reply(request_id, true, {"paused": true})
		"resume":
			if _paused:
				_revision += 1
			_paused = false
			_record("operator", "resume", {})
			_refresh_hud()
			return _reply(request_id, true, {"paused": false})
		"step":
			_tick += 1
			_revision += 1
			_record("operator", "step", {})
			_refresh_hud()
			return _reply(request_id, true, {"tick": _tick})
		"reset":
			_reset_world()
			_refresh_hud()
			return _reply(request_id, true, _debug_snapshot())
		"shutdown":
			_record("operator", "shutdown", {})
			get_tree().call_deferred("quit")
			return _reply(request_id, true, {"shutdown": true})
		_:
			return _reply(request_id, false, {}, "UNKNOWN_OPERATION")



# A separate v0.2 world contract. v0.1 stays untouched for comparison.
# Roles here are self-declared: NEVER expose this P5 test bridge remotely.
func _valid_uint(value) -> bool:
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		return false
	var number: float = float(value)
	return number >= 0.0 and number <= 2147483647.0 and number == floor(number)


func _reply_v2(request_id, ok: bool, data: Dictionary = {}, error: String = "") -> Dictionary:
	var response := {
		"protocol": PROTOCOL_V2, "id": request_id, "ok": ok,
		"epoch": _epoch, "revision": _revision,
		"event_seq": _event_seq, "tick": _tick,
	}
	if ok:
		response["data"] = data
	else:
		response["error"] = error
	return response


func _typed_observation() -> Dictionary:
	# Derive from the bounded sensor, NEVER _debug_snapshot().
	var sample := _agent_observation()
	var readings: Array[Dictionary] = []
	for item in sample["visible"]:
		match item["kind"]:
			"door":
				readings.append({
					"subject_ref": "lab.door.01",
					"predicate_ref": "state",
					"typed_value": {"type": "symbol", "value": item["state"]},
					"position": item["at"],
				})
			"actor":
				readings.append({
					"subject_ref": "lab.actor.human",
					"predicate_ref": "position",
					"typed_value": {
						"type": "grid_cell",
						"x": item["at"]["x"], "y": item["at"]["y"],
					},
				})
			"obstacle":
				readings.append({
					"subject_ref": "lab.obstacle.%d.%d" % [
						item["at"]["x"], item["at"]["y"],
					],
					"predicate_ref": "position",
					"typed_value": {
						"type": "grid_cell",
						"x": item["at"]["x"], "y": item["at"]["y"],
					},
				})
			"wall":
				readings.append({
					"subject_ref": "lab.wall.%d.%d" % [
						item["at"]["x"], item["at"]["y"],
					],
					"predicate_ref": "position",
					"typed_value": {
						"type": "grid_cell",
						"x": item["at"]["x"], "y": item["at"]["y"],
					},
				})
			"marker":
				readings.append({
					"subject_ref": "lab.marker.01",
					"predicate_ref": "position",
					"typed_value": {
						"type": "grid_cell",
						"x": item["at"]["x"], "y": item["at"]["y"],
					},
				})
	_sample_seq += 1
	var observation := {
		"schema": OBSERVATION_VERSION,
		"observation_id": "val_obs:%d:%d" % [_epoch, _sample_seq],
		"source_ref": "lab.sensor.anima.proximity",
		"producer_ref": "lab.godot",
		"observer_ref": "lab.actor.anima",
		"observed_at": {"epoch": _epoch, "tick": _tick},
		"world_revision": _revision,
		"event_cursor": _event_seq,
		"visibility": {"type": "manhattan_radius", "radius": SENSE_RADIUS},
		"self_position": sample["self"],
		"readings": readings,
	}
	_last_sample = observation.duplicate(true)
	_refresh_hud()
	return observation


func _valid_operation_key(value) -> bool:
	if typeof(value) != TYPE_STRING:
		return false
	if value.is_empty() or value.length() > 64:
		return false
	var allowed := "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
	for i in range(value.length()):
		if allowed.find(value.substr(i, 1)) == -1:
			return false
	return true


func _typed_action(req: Dictionary, request_id: int) -> Dictionary:
	var operation_id = req.get("operation_id")
	if not _valid_operation_key(operation_id):
		return _reply_v2(request_id, false, {}, "INVALID_OPERATION_ID")
	var action = req.get("action")
	if typeof(action) != TYPE_DICTIONARY or action.size() != 2:
		return _reply_v2(request_id, false, {}, "INVALID_ACTION")
	if action.get("schema") != ACTION_VERSION:
		return _reply_v2(request_id, false, {}, "INVALID_ACTION")
	var direction = action.get("direction")
	if typeof(direction) != TYPE_STRING or not direction in ["N", "S", "E", "W"]:
		return _reply_v2(request_id, false, {}, "INVALID_DIRECTION")
	if req.size() != 8:
		return _reply_v2(request_id, false, {}, "UNKNOWN_ACTION_FIELD")
	if not _valid_uint(req.get("expected_epoch")) or not _valid_uint(req.get("expected_revision")):
		return _reply_v2(request_id, false, {}, "INVALID_PRECONDITION")
	var expected_epoch: int = int(req["expected_epoch"])
	var expected_revision: int = int(req["expected_revision"])
	var fingerprint := "%s:%d:%d:%s" % [
		ACTION_VERSION, expected_epoch, expected_revision, direction,
	]
	if _action_ledger.has(operation_id):
		var prior: Dictionary = _action_ledger[operation_id]
		if prior["fingerprint"] != fingerprint:
			return _reply_v2(request_id, false, {}, "OPERATION_ID_CONFLICT")
		var replay: Dictionary = prior["receipt"].duplicate(true)
		replay["replayed"] = true
		return _reply_v2(request_id, true, replay)
	if expected_epoch != _epoch or expected_revision != _revision:
		return _reply_v2(request_id, false, {}, "STALE_WORLD")
	if _paused:
		return _reply_v2(request_id, false, {}, "PAUSED")
	if _action_ledger.size() >= MAX_ACTION_KEYS:
		return _reply_v2(request_id, false, {}, "LEDGER_CAPACITY")
	var movement := _move("anima", direction)
	var receipt := {
		"schema": "val.receipt/0.1",
		"operation_id": operation_id,
		"status": "APPLIED" if movement["moved"] else "BLOCKED",
		"effect_applied": movement["moved"],
		"reason": movement["reason"],
		"position": movement["position"],
		"event_id": movement["event_id"],
		"world_epoch": _epoch, "world_revision": _revision,
		"tick": _tick, "replayed": false,
	}
	_action_ledger[operation_id] = {
		"fingerprint": fingerprint,
		"receipt": receipt.duplicate(true),
	}
	return _reply_v2(request_id, true, receipt)



# P5-C operator fixture hooks. No agent capability may set world truth.
func _set_dynamic_obstacle(req: Dictionary, request_id: int) -> Dictionary:
	if req.size() != 6:
		return _reply_v2(request_id, false, {}, "INVALID_FIXTURE_REQUEST")
	var point = req.get("at")
	var blocked = req.get("blocked")
	if typeof(point) != TYPE_DICTIONARY or point.size() != 2:
		return _reply_v2(request_id, false, {}, "INVALID_OBSTACLE_CELL")
	if not _valid_uint(point.get("x")) or not _valid_uint(point.get("y")):
		return _reply_v2(request_id, false, {}, "INVALID_OBSTACLE_CELL")
	if typeof(blocked) != TYPE_BOOL:
		return _reply_v2(request_id, false, {}, "INVALID_OBSTACLE_STATE")
	var cell := Vector2i(int(point["x"]), int(point["y"]))
	if (
		not _inside(cell) or cell in _walls or cell == _door
		or cell == _anima or cell == _human or cell == _marker
	):
		return _reply_v2(request_id, false, {}, "INVALID_OBSTACLE_CELL")
	var present := cell in _dynamic_obstacles
	if blocked and not present and _dynamic_obstacles.size() >= MAX_DYNAMIC_OBSTACLES:
		return _reply_v2(request_id, false, {}, "OBSTACLE_CAPACITY")
	var changed: bool = bool(blocked) != present
	if changed:
		if bool(blocked):
			_dynamic_obstacles.append(cell)
		else:
			_dynamic_obstacles.erase(cell)
		_revision += 1
	_tick += 1
	var event := _record("operator", "set_obstacle", {
		"at": _cell(cell), "blocked": blocked, "changed": changed,
	})
	queue_redraw()
	_refresh_hud()
	return _reply_v2(request_id, true, {
		"at": _cell(cell), "blocked": blocked, "changed": changed,
		"event_id": event["event_id"],
	})


func _emit_noise(req: Dictionary, request_id: int) -> Dictionary:
	if req.size() != 5:
		return _reply_v2(request_id, false, {}, "INVALID_FIXTURE_REQUEST")
	var label = req.get("label")
	if not _valid_operation_key(label) or label.length() > 32:
		return _reply_v2(request_id, false, {}, "INVALID_NOISE_LABEL")
	# Ambient noise is an operator-authored test event, not agent evidence.
	# It advances logical time and event seq, NOT world state revision.
	_tick += 1
	var event := _record("ambient", "noise", {"label": label})
	_refresh_hud()
	return _reply_v2(request_id, true, {
		"event_id": event["event_id"], "label": label,
	})


func _typed_events(req: Dictionary, request_id: int) -> Dictionary:
	var from_seq = req.get("after_seq", 0)
	if not _valid_uint(from_seq):
		return _reply_v2(request_id, false, {}, "INVALID_CURSOR")
	var after_seq: int = int(from_seq)
	if after_seq > _event_seq:
		return _reply_v2(request_id, false, {}, "INVALID_CURSOR")
	var limit = req.get("limit", 8)
	if not _valid_uint(limit) or int(limit) < 1 or int(limit) > 8:
		return _reply_v2(request_id, false, {}, "INVALID_PAGE_LIMIT")
	if not _history.is_empty() and after_seq < int(_history[0]["event_seq"]) - 1:
		return _reply_v2(request_id, false, {}, "CURSOR_EXPIRED")
	var events: Array[Dictionary] = []
	for entry in _history:
		if int(entry["event_seq"]) > after_seq:
			events.append(entry.duplicate(true))
			if events.size() >= int(limit):
				break
	var next_cursor := after_seq
	if not events.is_empty():
		next_cursor = int(events[-1]["event_seq"])
	return _reply_v2(request_id, true, {
		"events": events, "next_cursor": next_cursor,
		"has_more": next_cursor < _event_seq,
	})


func _request_v2(req: Dictionary, request_id: int) -> Dictionary:
	var role = req.get("role")
	var op = req.get("op")
	if typeof(role) != TYPE_STRING or not role in ["agent", "operator"]:
		return _reply_v2(request_id, false, {}, "INVALID_ROLE")
	if typeof(op) != TYPE_STRING:
		return _reply_v2(request_id, false, {}, "INVALID_OPERATION")
	if op == "hello":
		return _reply_v2(request_id, true, {
			"world_version": WORLD_VERSION,
			"observation_schema": OBSERVATION_VERSION,
			"action_schema": ACTION_VERSION,
			"source_ref": "lab.sensor.anima.proximity",
			"capabilities": ["observe", "act"] if role == "agent" else [
				"inspect", "events", "set_door", "human_move", "reset",
				"pause", "resume", "step", "set_obstacle", "emit_noise",
			],
			"max_action_keys": MAX_ACTION_KEYS,
			"scenario": _scenario,
		})
	if role == "agent":
		match op:
			"observe":
				return _reply_v2(request_id, true, _typed_observation())
			"act":
				return _typed_action(req, request_id)
			_:
				return _reply_v2(request_id, false, {}, "FORBIDDEN")
	match op:
		"inspect":
			var snapshot := _debug_snapshot()
			snapshot["epoch"] = _epoch
			snapshot["revision"] = _revision
			snapshot["event_seq"] = _event_seq
			snapshot["last_agent_observation"] = _last_sample.duplicate(true)
			snapshot["scenario"] = _scenario
			var obstacles: Array[Dictionary] = []
			for point in _dynamic_obstacles:
				obstacles.append(_cell(point))
			snapshot["dynamic_obstacles"] = obstacles
			return _reply_v2(request_id, true, snapshot)
		"events":
			return _typed_events(req, request_id)
		"set_obstacle":
			return _set_dynamic_obstacle(req, request_id)
		"emit_noise":
			return _emit_noise(req, request_id)
		"human_move", "set_door", "pause", "resume", "step", "reset":
			# Operator interventions reuse the verified P5-A fixture.
			var legacy := req.duplicate(true)
			legacy["protocol"] = PROTOCOL
			var response := _request(JSON.stringify(legacy))
			return _reply_v2(
				request_id, bool(response["ok"]), response.get("data", {}),
				str(response.get("error", "")),
			)
		_:
			return _reply_v2(request_id, false, {}, "UNKNOWN_OPERATION")


func _reply(request_id, ok: bool, data: Dictionary, error: String = "") -> Dictionary:
	var response := {
		"protocol": PROTOCOL, "id": request_id,
		"ok": ok, "tick": _tick,
	}
	if ok:
		response["data"] = data
	else:
		response["error"] = error
	return response


func _cell(point: Vector2i) -> Dictionary:
	return {"x": point.x, "y": point.y}


func _distance(a: Vector2i, b: Vector2i) -> int:
	return absi(a.x - b.x) + absi(a.y - b.y)


func _inside(point: Vector2i) -> bool:
	return point.x >= 0 and point.y >= 0 and point.x < WIDTH and point.y < HEIGHT


func _move(who: String, direction: String) -> Dictionary:
	var delta := Vector2i.ZERO
	match direction:
		"N":
			delta = Vector2i(0, -1)
		"S":
			delta = Vector2i(0, 1)
		"E":
			delta = Vector2i(1, 0)
		"W":
			delta = Vector2i(-1, 0)
	var before := _anima if who == "anima" else _human
	var other := _human if who == "anima" else _anima
	var target := before + delta
	var reason := "ok"
	if not _inside(target) or target in _walls or target in _dynamic_obstacles:
		reason = "wall"
	elif target == other:
		reason = "other_actor"
	elif target == _door and not _door_open:
		reason = "closed_door"
	var moved := reason == "ok"
	if moved:
		if who == "anima":
			_anima = target
		else:
			_human = target
		_revision += 1
	_tick += 1
	var event := _record(who, "move", {
		"direction": direction, "moved": moved, "reason": reason,
	})
	queue_redraw()
	_refresh_hud()
	return {
		"moved": moved, "position": _cell(target if moved else before),
		"reason": reason, "event_id": event["event_id"], "revision": _revision,
	}


func _agent_observation() -> Dictionary:
	var visible: Array[Dictionary] = []
	for wall in _walls:
		if _distance(_anima, wall) <= SENSE_RADIUS:
			visible.append({"kind": "wall", "at": _cell(wall)})
	for obstacle in _dynamic_obstacles:
		if _distance(_anima, obstacle) <= SENSE_RADIUS:
			visible.append({"kind": "obstacle", "at": _cell(obstacle)})
	if _distance(_anima, _door) <= SENSE_RADIUS:
		visible.append({
			"kind": "door", "at": _cell(_door),
			"state": "open" if _door_open else "closed",
		})
	if _distance(_anima, _marker) <= SENSE_RADIUS:
		visible.append({"kind": "marker", "at": _cell(_marker)})
	if _distance(_anima, _human) <= SENSE_RADIUS:
		visible.append({"kind": "actor", "name": "human", "at": _cell(_human)})
	_record("sensor.anima", "observe", {"visible_count": visible.size()})
	return {
		"observer": "anima", "self": _cell(_anima),
		"radius": SENSE_RADIUS, "visible": visible,
	}


func _debug_snapshot() -> Dictionary:
	var wall_list: Array[Dictionary] = []
	for p in _walls:
		wall_list.append(_cell(p))
	return {
		"world_version": WORLD_VERSION, "seed": _seed,
		"paused": _paused, "tick": _tick,
		"human": _cell(_human), "anima": _cell(_anima),
		"door": {"at": _cell(_door), "open": _door_open},
		"marker": _cell(_marker), "walls": wall_list,
	}


func _record(actor: String, event_type: String, details: Dictionary) -> Dictionary:
	_event_seq += 1
	var record := {
		"event_id": "val_evt:%d" % _event_seq,
		"event_seq": _event_seq, "epoch": _epoch, "revision": _revision,
		"tick": _tick, "actor": actor, "event": event_type,
		"details": details.duplicate(true),
	}
	_history.append(record)
	if _history.size() > MAX_EVENTS:
		_history.pop_front()
	return record


func _refresh_hud() -> void:
	if _hud != null:
		if _ui_mode == "normal":
			_hud.text = "Human (blue): arrows / WASD  •  E: nearby door\n"
			_hud.text += "ANIMA (green): Python bridge  •  F3: Debug panel"
		else:
			_refresh_debug_hud()
	if _diagnostics != null and _ui_mode == "debug":
		_refresh_diagnostics()


func _refresh_debug_hud() -> void:
	if _hud != null:
		var pause_word := "PAUSED" if _paused else "RUNNING"
		var door_word := "OPEN" if _door_open else "CLOSED"
		_hud.text = "Human (blue): arrows / WASD  •  E opens nearby door\n"
		_hud.text += "ANIMA (green): Python bridge only  •  Tick: %d\n" % _tick
		_hud.text += "Door: %s  |  %s  |  seed: %d  |  port: %d" % [
			door_word, pause_word, _seed, _port,
		]
func _refresh_diagnostics() -> void:
	if _diagnostics != null:
		_diagnostics.text = "OPERATOR / WORLD TRUTH\n"
		_diagnostics.text += "Epoch: %d\nRevision: %d\nTick: %d\n" % [
			_epoch, _revision, _tick,
		]
		_diagnostics.text += "Human: (%d,%d)\n" % [_human.x, _human.y]
		_diagnostics.text += "ANIMA: (%d,%d)\n" % [_anima.x, _anima.y]
		_diagnostics.text += "Door: %s\n" % ("open" if _door_open else "closed")
		_diagnostics.text += "Scenario: %s\n" % _scenario
		_diagnostics.text += "Dynamic blocks: %d\n" % _dynamic_obstacles.size()
		_diagnostics.text += "Event seq: %d\n\n" % _event_seq
		_diagnostics.text += "ANIMA / LAST SENSOR\n"
		if _last_sample.is_empty():
			_diagnostics.text += "No typed sample yet\n"
		else:
			_diagnostics.text += "ID: %s\n" % _last_sample["observation_id"]
			_diagnostics.text += "Observed tick: %d\n" % _last_sample["observed_at"]["tick"]
			_diagnostics.text += "Readings: %d\n" % _last_sample["readings"].size()
		_diagnostics.text += "\nLAST EVENTS\n"
		var start: int = maxi(0, _history.size() - 5)
		for record in _history.slice(start, _history.size()):
			_diagnostics.text += "%d  %s / %s\n" % [
				record["event_seq"], record["actor"], record["event"],
			]


func _unhandled_key_input(event: InputEvent) -> void:
	if not (event is InputEventKey):
		return
	if not event.pressed or event.echo:
		return
	if event.keycode == KEY_F3:
		_set_ui_mode("normal" if _ui_mode == "debug" else "debug")
		return
	if _paused:
		return
	var direction := ""
	match event.keycode:
		KEY_W, KEY_UP:
			direction = "N"
		KEY_S, KEY_DOWN:
			direction = "S"
		KEY_A, KEY_LEFT:
			direction = "W"
		KEY_D, KEY_RIGHT:
			direction = "E"
		KEY_E:
			if _distance(_human, _door) <= 1 and (
				not _door_open or (_human != _door and _anima != _door)
			):
				_tick += 1
				_revision += 1
				_door_open = not _door_open
				_record("human", "toggle_door", {"open": _door_open})
				queue_redraw()
				_refresh_hud()
	if direction != "":
		_move("human", direction)


func _draw() -> void:
	draw_rect(
		Rect2(Vector2.ZERO, Vector2(WIDTH * CELL, HEIGHT * CELL)),
		Color("#152131"),
	)
	for x in range(WIDTH):
		for y in range(HEIGHT):
			var rect := Rect2(Vector2(x * CELL, y * CELL), Vector2(CELL, CELL))
			draw_rect(rect, Color("#344457"), false, 1.0)
	for p in _walls:
		draw_rect(
			Rect2(Vector2(p.x * CELL + 2, p.y * CELL + 2), Vector2(CELL - 4, CELL - 4)),
			Color("#6a7687"),
		)
	for p in _dynamic_obstacles:
		draw_rect(
			Rect2(Vector2(p.x * CELL + 6, p.y * CELL + 6), Vector2(CELL - 12, CELL - 12)),
			Color("#d34d61"),
		)
	var door_color := Color("#3ebc80") if _door_open else Color("#e7a54c")
	draw_rect(
		Rect2(
			Vector2(_door.x * CELL + 8, _door.y * CELL + 8),
			Vector2(CELL - 16, CELL - 16),
		),
		door_color,
	)
	draw_circle(
		Vector2(_marker.x * CELL + CELL / 2, _marker.y * CELL + CELL / 2),
		8.0, Color("#e8d85f"),
	)
	draw_circle(
		Vector2(_human.x * CELL + CELL / 2, _human.y * CELL + CELL / 2),
		17.0, Color("#54a2f1"),
	)
	draw_circle(
		Vector2(_anima.x * CELL + CELL / 2, _anima.y * CELL + CELL / 2),
		17.0, Color("#72da8c"),
	)
