extends Control
## Human-only, isolated UI transport for E2.5b Visual Decision Runner.
## Fetches *already verified* Python telemetry; does not create Raw, Core
## actions, requests to Godot operator inspect or LLM/agent observations.
## Authentication is an ephemeral token passed by the trusted launcher via env.

const STATE_SCHEMA := "anima.lab.visual_runner_state/0.1"

var _port := 0
var _token := ""
var _poll: HTTPRequest
var _command: HTTPRequest
var _timer: Timer
var _status: Label
var _buttons: Array[Button] = []


func configure(port: int, key: String) -> void:
	_port = port
	_token = key


func _ready() -> void:
	var names := ["STEP", "RUN", "PAUSE"]
	for index in range(names.size()):
		var button := Button.new()
		button.position = Vector2(3 + index * 88, 0)
		button.size = Vector2(82, 29)
		button.text = names[index]
		var action: String = names[index].to_lower()
		button.pressed.connect(func() -> void: _send(action))
		add_child(button)
		_buttons.append(button)
	var memory := Button.new()
	memory.position = Vector2(3, 34)
	memory.size = Vector2(127, 28)
	memory.text = "TOGGLE MEMORY"
	memory.pressed.connect(func() -> void: _send("memory"))
	add_child(memory)
	_buttons.append(memory)
	_status = Label.new()
	_status.position = Vector2(137, 39)
	_status.size = Vector2(135, 25)
	_status.add_theme_font_size_override("font_size", 11)
	_status.text = "Connecting..."
	add_child(_status)
	_poll = HTTPRequest.new()
	_poll.timeout = 1.5
	add_child(_poll)
	_poll.request_completed.connect(_on_poll)
	_command = HTTPRequest.new()
	_command.timeout = 1.5
	add_child(_command)
	_command.request_completed.connect(_on_command)
	_timer = Timer.new()
	_timer.wait_time = 0.45
	_timer.one_shot = false
	_timer.timeout.connect(_fetch)
	add_child(_timer)
	_timer.start()
	_fetch()


func _api(command: String) -> String:
	return "http://127.0.0.1:%d/%s" % [_port, command]


func _headers() -> PackedStringArray:
	return PackedStringArray(["X-ANIMA-Control-Key: " + _token])


func _fetch() -> void:
	if _poll.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var err: Error = _poll.request(_api("state"), _headers(), HTTPClient.METHOD_GET)
	if err != OK:
		_status.text = "API: offline"
		get_parent().call("_visual_runner_error", "HTTP request error")


func _send(command: String) -> void:
	if _command.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	for button in _buttons:
		button.disabled = true
	var err: Error = _command.request(_api(command), _headers(), HTTPClient.METHOD_POST, "")
	if err != OK:
		_status.text = "Control failed"
		for button in _buttons:
			button.disabled = false


func _on_command(result: int, code: int, _headers_in: PackedStringArray, _body: PackedByteArray) -> void:
	for button in _buttons:
		button.disabled = false
	if result != HTTPRequest.RESULT_SUCCESS or code != 202:
		_status.text = "Control rejected"
	else:
		_status.text = "Command queued"
	_fetch()


func _on_poll(result: int, code: int, _headers_in: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_status.text = "API offline"
		get_parent().call("_visual_runner_error", "API disconnected")
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		_status.text = "Invalid state"
		get_parent().call("_visual_runner_error", "Invalid control JSON")
		return
	var state: Dictionary = parsed
	if state.get("schema") != STATE_SCHEMA or state.get("runner_connected") != true:
		_status.text = "Schema mismatch"
		get_parent().call("_visual_runner_error", "Control schema mismatch")
		return
	var active := "RUN" if state.get("run_enabled") == true else "PAUSED"
	_status.text = active
	get_parent().call("_visual_runner_update", state)
