import hashlib
import json
import multiprocessing
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anima.agent.contracts import Action, ExecutionReceipt
from anima.agent.store import AgentStore
from anima.agent.tools import ToolDescriptor, ToolOutputError, ToolRegistry


MAX_PATH_CHARS = 512
MAX_LIST_ENTRIES = 512
MAX_FILE_BYTES = 1_000_000
STANDARD_TOOL_VERSION = "1"

SANDBOX_RELATIVE_PATH_PATTERN = r"^[^/].*$"
SANDBOX_PATH_DESCRIPTION = (
    "Sandbox-relative path. Use '.' for the sandbox root when listing, "
    "or a path such as 'result.txt' for files. Never prefix the path "
    "with '/' or 'sandbox/'."
)


class ExecutionRejectedError(ValueError):
    """The Action cannot cross the Executor trust boundary."""


class UncertainOperationError(RuntimeError):
    """An ambiguous side effect cannot be retried automatically."""


class SandboxToolError(Exception):
    """Expected Tool failure with explicit side-effect knowledge."""

    def __init__(self, code, message, *, effect_possible=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.effect_possible = bool(effect_possible)


@dataclass(frozen=True, slots=True)
class SandboxHandler:
    execute: object
    reconcile: object | None = None
    replay_output: object | None = None

    def __post_init__(self):
        if not callable(self.execute):
            raise TypeError("SandboxHandler execute must be callable")
        if self.reconcile is not None and not callable(self.reconcile):
            raise TypeError("SandboxHandler reconcile must be callable")
        if self.replay_output is not None and not callable(self.replay_output):
            raise TypeError("SandboxHandler replay_output must be callable")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def action_request_hash(action):
    if not isinstance(action, Action):
        raise TypeError("action_request_hash() requires an Action")
    payload = {
        "tool": action.tool,
        "tool_version": action.tool_version,
        "arguments": action.to_dict()["arguments"],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def operation_kind(action):
    if not isinstance(action, Action):
        raise TypeError("operation_kind() requires an Action")
    return f"tool:{action.tool}@{action.tool_version}"


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def _normalize_relative_path(raw_path, *, allow_root):
    if not isinstance(raw_path, str) or not raw_path:
        raise SandboxToolError("INVALID_PATH", "path must be a non-empty string")
    if len(raw_path) > MAX_PATH_CHARS:
        raise SandboxToolError("INVALID_PATH", "path exceeds sandbox limit")
    if "\x00" in raw_path:
        raise SandboxToolError("INVALID_PATH", "path contains NUL")

    relative = Path(raw_path)
    if relative.is_absolute():
        raise SandboxToolError("SANDBOX_ESCAPE", "absolute paths are forbidden")
    if ".." in relative.parts:
        raise SandboxToolError("SANDBOX_ESCAPE", "parent traversal is forbidden")

    normalized = relative.as_posix()
    if normalized in {"", "."}:
        if not allow_root:
            raise SandboxToolError("INVALID_PATH", "sandbox root is not a file path")
        return "."
    return normalized


def _resolve_path(root, raw_path, *, allow_root=False, reject_symlinks=False):
    root_path = Path(root).resolve()
    relative = _normalize_relative_path(raw_path, allow_root=allow_root)
    unresolved = root_path if relative == "." else root_path / relative

    if reject_symlinks and relative != ".":
        cursor = root_path
        for part in Path(relative).parts:
            cursor = cursor / part
            if cursor.exists() or cursor.is_symlink():
                if cursor.is_symlink():
                    raise SandboxToolError(
                        "SYMLINK_WRITE_FORBIDDEN",
                        "writes through symlinks are forbidden",
                    )

    resolved = unresolved.resolve(strict=False)
    if not resolved.is_relative_to(root_path):
        raise SandboxToolError("SANDBOX_ESCAPE", "resolved path leaves sandbox root")
    if resolved == root_path and not allow_root:
        raise SandboxToolError("INVALID_PATH", "sandbox root is not a file path")
    return root_path, resolved, relative


def _entry_kind(path):
    if path.is_symlink():
        return "symlink"
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    return "other"


def _fs_list(root, arguments, operation_id):
    del operation_id
    raw_path = arguments.get("path", ".")
    _, target, relative = _resolve_path(root, raw_path, allow_root=True)
    if not target.exists():
        raise SandboxToolError("NOT_FOUND", f"directory does not exist: {relative}")
    if not target.is_dir():
        raise SandboxToolError("NOT_DIRECTORY", f"not a directory: {relative}")

    entries = []
    truncated = False
    for entry in sorted(target.iterdir(), key=lambda item: item.name):
        if entry.name.startswith(".anima-aop_") and entry.name.endswith(".tmp"):
            continue
        if len(entries) >= MAX_LIST_ENTRIES:
            truncated = True
            break
        entries.append({"name": entry.name, "kind": _entry_kind(entry)})
    return {"path": relative, "entries": entries, "truncated": truncated}


def _fs_read(root, arguments, operation_id):
    del operation_id
    _, target, relative = _resolve_path(root, arguments["path"], allow_root=False)
    if not target.exists():
        raise SandboxToolError("NOT_FOUND", f"file does not exist: {relative}")
    if not target.is_file():
        raise SandboxToolError("NOT_FILE", f"not a regular file: {relative}")

    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        raise SandboxToolError("FILE_TOO_LARGE", f"file exceeds {MAX_FILE_BYTES} bytes")
    payload = target.read_bytes()
    if len(payload) > MAX_FILE_BYTES:
        raise SandboxToolError("FILE_TOO_LARGE", f"file exceeds {MAX_FILE_BYTES} bytes")
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SandboxToolError("UNSUPPORTED_ENCODING", "file is not valid UTF-8") from error
    return {
        "path": relative,
        "content": content,
        "bytes": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _write_output(relative, payload):
    return {
        "path": relative,
        "bytes_written": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _fs_write(root, arguments, operation_id):
    root_path, target, relative = _resolve_path(
        root,
        arguments["path"],
        allow_root=False,
        reject_symlinks=True,
    )
    payload = arguments["content"].encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise SandboxToolError("FILE_TOO_LARGE", f"content exceeds {MAX_FILE_BYTES} bytes")
    if target.exists() and target.is_dir():
        raise SandboxToolError("TARGET_IS_DIRECTORY", f"target is a directory: {relative}")
    if not target.parent.exists():
        raise SandboxToolError("PARENT_NOT_FOUND", f"parent directory does not exist: {relative}")
    if not target.parent.is_dir():
        raise SandboxToolError("PARENT_NOT_DIRECTORY", f"parent is not a directory: {relative}")
    if not target.parent.is_relative_to(root_path):
        raise SandboxToolError("SANDBOX_ESCAPE", "write parent leaves sandbox root")

    temp = target.parent / f".anima-{operation_id}.tmp"
    try:
        if temp.exists() or temp.is_symlink():
            temp.unlink()
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError as error:
        try:
            if temp.exists() or temp.is_symlink():
                temp.unlink()
        except OSError:
            pass
        raise SandboxToolError("WRITE_FAILED", str(error), effect_possible=False) from error
    return _write_output(relative, payload)


def _fs_write_reconcile(root, arguments, operation_id):
    del operation_id
    _, target, relative = _resolve_path(
        root,
        arguments["path"],
        allow_root=False,
        reject_symlinks=True,
    )
    payload = arguments["content"].encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise SandboxToolError("FILE_TOO_LARGE", f"content exceeds {MAX_FILE_BYTES} bytes")
    if not target.exists():
        return "retry", None
    if not target.is_file():
        raise SandboxToolError("RECONCILIATION_BLOCKED", f"target is not a file: {relative}")
    if target.stat().st_size != len(payload):
        return "retry", None
    current = target.read_bytes()
    if current == payload:
        return "succeeded", _write_output(relative, payload)
    return "retry", None


def _fs_write_replay_output(root, arguments, operation_id):
    del root, operation_id
    relative = _normalize_relative_path(arguments["path"], allow_root=False)
    payload = arguments["content"].encode("utf-8")
    return _write_output(relative, payload)


def sandbox_tool_descriptors():
    entry_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": MAX_PATH_CHARS},
            "kind": {
                "type": "string",
                "enum": ["file", "directory", "symlink", "other"],
            },
        },
        "required": ["name", "kind"],
        "additionalProperties": False,
    }
    return (
        ToolDescriptor(
            name="fs.list",
            version=STANDARD_TOOL_VERSION,
            description="List one directory inside the Agent filesystem sandbox.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATH_CHARS,
                        "pattern": SANDBOX_RELATIVE_PATH_PATTERN,
                        "description": SANDBOX_PATH_DESCRIPTION,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "entries": {
                        "type": "array",
                        "items": entry_schema,
                        "maxItems": MAX_LIST_ENTRIES,
                    },
                    "truncated": {"type": "boolean"},
                },
                "required": ["path", "entries", "truncated"],
                "additionalProperties": False,
            },
            effect_class="read_only",
            idempotency="repeat_safe",
            effort_hint="cheap",
            timeout_seconds=2.0,
            sandbox_scope=("filesystem",),
        ),
        ToolDescriptor(
            name="fs.read",
            version=STANDARD_TOOL_VERSION,
            description="Read one bounded UTF-8 file inside the Agent filesystem sandbox.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATH_CHARS,
                        "pattern": SANDBOX_RELATIVE_PATH_PATTERN,
                        "description": SANDBOX_PATH_DESCRIPTION,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "bytes": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
                "required": ["path", "content", "bytes", "sha256"],
                "additionalProperties": False,
            },
            effect_class="read_only",
            idempotency="repeat_safe",
            effort_hint="cheap",
            timeout_seconds=2.0,
            sandbox_scope=("filesystem",),
        ),
        ToolDescriptor(
            name="fs.write",
            version=STANDARD_TOOL_VERSION,
            description="Atomically write one bounded UTF-8 file inside the Agent filesystem sandbox.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_PATH_CHARS,
                        "pattern": SANDBOX_RELATIVE_PATH_PATTERN,
                        "description": SANDBOX_PATH_DESCRIPTION,
                    },
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "bytes_written": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
                "required": ["path", "bytes_written", "sha256"],
                "additionalProperties": False,
            },
            effect_class="reversible_write",
            idempotency="keyed",
            effort_hint="normal",
            timeout_seconds=2.0,
            sandbox_scope=("filesystem",),
        ),
    )


def build_sandbox_registry():
    return ToolRegistry(sandbox_tool_descriptors())


def _standard_handlers():
    return {
        ("fs.list", STANDARD_TOOL_VERSION): SandboxHandler(_fs_list),
        ("fs.read", STANDARD_TOOL_VERSION): SandboxHandler(_fs_read),
        ("fs.write", STANDARD_TOOL_VERSION): SandboxHandler(
            _fs_write,
            reconcile=_fs_write_reconcile,
            replay_output=_fs_write_replay_output,
        ),
    }


def _worker_entry(handler, root, arguments, operation_id, send_connection):
    try:
        try:
            output = handler(root, arguments, operation_id)
        except SandboxToolError as error:
            message = {
                "kind": "tool_error",
                "code": error.code,
                "message": error.message,
                "effect_possible": error.effect_possible,
            }
        except BaseException as error:
            message = {
                "kind": "system_error",
                "code": "EXECUTION_ERROR",
                "message": f"{type(error).__name__}: {error}",
                "effect_possible": True,
            }
        else:
            message = {"kind": "success", "output": output}
        send_connection.send(message)
    finally:
        send_connection.close()


class SandboxExecutor:
    """Execute trusted Tool handlers while preserving AgentOperation recovery state."""

    def __init__(self, *, root, registry, store, handlers=None):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("SandboxExecutor registry must be a ToolRegistry")
        if not isinstance(store, AgentStore):
            raise TypeError("SandboxExecutor store must be an AgentStore")
        root = Path(root).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("SandboxExecutor root must be an existing directory")

        selected_handlers = _standard_handlers() if handlers is None else dict(handlers)
        for key, handler in selected_handlers.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not all(isinstance(item, str) and item for item in key)
            ):
                raise ValueError("SandboxExecutor handler keys must be (tool, version)")
            if not isinstance(handler, SandboxHandler):
                raise TypeError("SandboxExecutor handlers must be SandboxHandler values")

        self.root = root
        self.registry = registry
        self.store = store
        self.handlers = selected_handlers

    def _validate_binding(self, action, descriptor, operation):
        if operation is None:
            raise ExecutionRejectedError(
                "Action requires a persisted AgentOperation before execution"
            )
        expected = {
            "run_id": action.run_id,
            "step_id": action.step_id,
            "action_id": action.public_id,
            "operation_kind": operation_kind(action),
            "request_hash": action_request_hash(action),
            "idempotency_class": descriptor.idempotency,
        }
        for field, value in expected.items():
            if operation[field] != value:
                raise ExecutionRejectedError(
                    f"AgentOperation {field} does not match Action execution intent"
                )

    def _receipt(self, action, *, status, started_at, output=None, code=None, message=None):
        return ExecutionReceipt.create(
            action=action,
            status=status,
            started_at=started_at,
            finished_at=_now(),
            output=output,
            error_code=code,
            error_message=message,
        )

    def _mark_after_failure(self, action, descriptor, *, reason, effect_possible):
        to_status = (
            "uncertain"
            if effect_possible and descriptor.effect_class != "read_only"
            else "failed"
        )
        self.store.transition_operation(action.operation_id, to_status, reason=reason)

    def _invoke(self, action, descriptor, handler):
        methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
        receive_connection, send_connection = context.Pipe(duplex=False)
        arguments = action.to_dict()["arguments"]
        process = context.Process(
            target=_worker_entry,
            args=(handler.execute, str(self.root), arguments, action.operation_id, send_connection),
        )
        process.daemon = True
        started_at = _now()
        try:
            process.start()
        except BaseException as error:
            send_connection.close()
            receive_connection.close()
            self._mark_after_failure(
                action,
                descriptor,
                reason=f"worker start failed: {error}",
                effect_possible=False,
            )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code="WORKER_START_FAILED",
                message=str(error),
            )
        send_connection.close()

        process.join(descriptor.timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join()
            receive_connection.close()
            effect_possible = descriptor.effect_class != "read_only"
            self._mark_after_failure(
                action,
                descriptor,
                reason="tool execution timed out",
                effect_possible=effect_possible,
            )
            return self._receipt(
                action,
                status="timeout",
                started_at=started_at,
                code="TIMEOUT",
                message=f"tool exceeded {descriptor.timeout_seconds:g}s timeout",
            )

        if not receive_connection.poll(0.1):
            receive_connection.close()
            effect_possible = descriptor.effect_class != "read_only"
            self._mark_after_failure(
                action,
                descriptor,
                reason="worker exited without a result",
                effect_possible=effect_possible,
            )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code="WORKER_EXIT",
                message=f"worker exited with code {process.exitcode}",
            )

        result = receive_connection.recv()
        receive_connection.close()
        if result["kind"] == "tool_error":
            effect_possible = bool(result.get("effect_possible"))
            self._mark_after_failure(
                action,
                descriptor,
                reason=f"tool error {result['code']}: {result['message']}",
                effect_possible=effect_possible,
            )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code=result["code"],
                message=result["message"],
            )

        if result["kind"] != "success":
            effect_possible = descriptor.effect_class != "read_only"
            self._mark_after_failure(
                action,
                descriptor,
                reason=result.get("message", "worker system error"),
                effect_possible=effect_possible,
            )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code=result.get("code", "EXECUTION_ERROR"),
                message=result.get("message", "worker system error"),
            )

        output = result.get("output")
        try:
            descriptor.validate_output(output)
        except ToolOutputError as error:
            effect_possible = descriptor.effect_class != "read_only"
            self._mark_after_failure(
                action,
                descriptor,
                reason=f"invalid tool output: {error}",
                effect_possible=effect_possible,
            )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code="INVALID_TOOL_OUTPUT",
                message=str(error),
            )

        self.store.transition_operation(
            action.operation_id,
            "succeeded",
            reason="tool execution succeeded",
        )
        return self._receipt(
            action,
            status="succeeded",
            started_at=started_at,
            output=output,
        )

    def execute(self, action):
        if not isinstance(action, Action):
            raise TypeError("SandboxExecutor.execute() requires an Action")
        descriptor = self.registry.get(action.tool, action.tool_version)
        descriptor.validate_input(action.to_dict()["arguments"])
        handler = self.handlers.get((action.tool, action.tool_version))
        if handler is None:
            raise ExecutionRejectedError(
                f"No trusted Executor handler for {action.tool}@{action.tool_version}"
            )

        operation = self.store.get_operation(action.operation_id)
        self._validate_binding(action, descriptor, operation)
        status = operation["status"]

        if status == "succeeded":
            if descriptor.idempotency == "keyed" and handler.replay_output is not None:
                started_at = _now()
                output = handler.replay_output(
                    str(self.root),
                    action.to_dict()["arguments"],
                    action.operation_id,
                )
                descriptor.validate_output(output)
                return self._receipt(
                    action,
                    status="succeeded",
                    started_at=started_at,
                    output=output,
                )
            if descriptor.idempotency != "repeat_safe":
                raise ExecutionRejectedError(
                    "Completed operation has no deterministic replay output"
                )
            started_at = _now()
            receive_connection, send_connection = multiprocessing.Pipe(duplex=False)
            del receive_connection, send_connection, started_at
            raise ExecutionRejectedError(
                "repeat-safe completed operation requires a new AgentOperation in Stage 4.4"
            )

        if status in {"failed", "cancelled"}:
            raise ExecutionRejectedError(
                f"Terminal AgentOperation cannot execute again: {status}"
            )

        if status == "executing":
            self.store.transition_operation(
                action.operation_id,
                "uncertain",
                reason="recovered operation found in executing state",
            )
            status = "uncertain"

        if status == "uncertain":
            if descriptor.idempotency == "none":
                raise UncertainOperationError(
                    "non-idempotent uncertain operation requires external reconciliation"
                )
            if descriptor.idempotency == "keyed":
                if handler.reconcile is None:
                    raise UncertainOperationError(
                        "keyed uncertain operation has no reconciler"
                    )
                try:
                    outcome, output = handler.reconcile(
                        str(self.root),
                        action.to_dict()["arguments"],
                        action.operation_id,
                    )
                except SandboxToolError as error:
                    raise UncertainOperationError(
                        f"cannot reconcile operation: {error.code}: {error.message}"
                    ) from error
                if outcome == "succeeded":
                    descriptor.validate_output(output)
                    self.store.transition_operation(
                        action.operation_id,
                        "succeeded",
                        reason="uncertain side effect reconciled as already applied",
                    )
                    started_at = _now()
                    return self._receipt(
                        action,
                        status="succeeded",
                        started_at=started_at,
                        output=output,
                    )
                if outcome != "retry":
                    raise UncertainOperationError(
                        f"unsupported reconciliation outcome: {outcome!r}"
                    )
            self.store.transition_operation(
                action.operation_id,
                "executing",
                reason="safe retry after recovery",
            )
        elif status == "prepared":
            self.store.transition_operation(
                action.operation_id,
                "executing",
                reason="tool execution started",
            )
        else:
            raise ExecutionRejectedError(f"Unsupported AgentOperation state: {status}")

        return self._invoke(action, descriptor, handler)
