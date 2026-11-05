extends Node2D
## P5-A independent world. ANIMA Core is intentionally NOT imported.
## The loopback bridge is a feasibility protocol, not authentication.

const PROTOCOL := "val.bridge/0.1"
const WORLD_VERSION := "p5a-grid/0.1"
const WIDTH := 12
const HEIGHT := 8
const CELL := 56
const SENSE_RADIUS := 3
const MAX_LINE_BYTES := 8192
const MAX_EVENTS := 256

var _server: TCPServer = TCPServer.new()
var _peer: StreamPeerTCP = null
var _buffer := ""
var _port := 46019
var _seed := 7
var _tick := 0
var _paused := false
var _human := Vector2i(2, 2)
var _anima := Vector2i(9, 5)
var _door := Vector2i(6, 3)
var _door_open := false
var _marker := Vector2i(8, 2)
var _walls: Array[Vector2i] = []
var _history: Array[Dictionary] = []
var _hud: Label


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_parse_args()
	_reset_world()
	_hud = Label.new()
	_hud.position = Vector2(24, 466)
	_hud.add_theme_font_size_override("font_size", 17)
	add_child(_hud)
	_refresh_hud()
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
		i += 1
	if _port < 1024 or _port > 65535 or _seed < 0:
		push_error("VAL: invalid port or seed")
		get_tree().quit(2)


func _reset_world() -> void:
	_tick = 0
	_paused = false
	_human = Vector2i(2, 2)
	_anima = Vector2i(9, 5)
	_door_open = false
	_walls.clear()
	_history.clear()
	for x in range(WIDTH):
		_walls.append(Vector2i(x, 0))
		_walls.append(Vector2i(x, HEIGHT - 1))
	for y in range(1, HEIGHT - 1):
		_walls.append(Vector2i(0, y))
		_walls.append(Vector2i(WIDTH - 1, y))
	_walls.append(Vector2i(4, 3))
	_walls.append(Vector2i(4, 4))
	var choices: Array[Vector2i] = [
		Vector2i(8, 2), Vector2i(8, 4), Vector2i(3, 5),
	]
	var rng := RandomNumberGenerator.new()
	rng.seed = _seed
	_marker = choices[rng.randi_range(0, choices.size() - 1)]
	_record("lab", "reset", {"seed": _seed, "world_version": WORLD_VERSION})
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
	var request_id = req.get("id")
	if typeof(request_id) != TYPE_INT or int(request_id) < 0:
		return _reply(request_id, false, {}, "INVALID_ID")
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
			return _reply(request_id, true, {"events": _history.duplicate(true)})
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
			_door_open = bool(desired)
			_record("operator", "set_door", {"open": _door_open})
			queue_redraw()
			_refresh_hud()
			return _reply(request_id, true, {"open": _door_open})
		"pause":
			_paused = true
			_record("operator", "pause", {})
			_refresh_hud()
			return _reply(request_id, true, {"paused": true})
		"resume":
			_paused = false
			_record("operator", "resume", {})
			_refresh_hud()
			return _reply(request_id, true, {"paused": false})
		"step":
			_tick += 1
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
	if not _inside(target) or target in _walls:
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
	_tick += 1
	_record(who, "move", {
		"direction": direction, "moved": moved, "reason": reason,
	})
	queue_redraw()
	_refresh_hud()
	return {"moved": moved, "position": _cell(target if moved else before), "reason": reason}


func _agent_observation() -> Dictionary:
	var visible: Array[Dictionary] = []
	for wall in _walls:
		if _distance(_anima, wall) <= SENSE_RADIUS:
			visible.append({"kind": "wall", "at": _cell(wall)})
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


func _record(actor: String, event_type: String, details: Dictionary) -> void:
	_history.append({
		"tick": _tick, "actor": actor, "event": event_type, "details": details,
	})
	if _history.size() > MAX_EVENTS:
		_history.pop_front()


func _refresh_hud() -> void:
	if _hud != null:
		var pause_word := "PAUSED" if _paused else "RUNNING"
		var door_word := "OPEN" if _door_open else "CLOSED"
		_hud.text = "Human (blue): arrows / WASD  •  E opens nearby door\n"
		_hud.text += "ANIMA (green): Python bridge only  •  Tick: %d\n" % _tick
		_hud.text += "Door: %s  |  %s  |  seed: %d  |  port: %d" % [
			door_word, pause_word, _seed, _port,
		]


func _unhandled_key_input(event: InputEvent) -> void:
	if not (event is InputEventKey):
		return
	if not event.pressed or event.echo or _paused:
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
			if _distance(_human, _door) <= 1:
				_tick += 1
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
