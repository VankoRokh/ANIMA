"""Bounded Stage 6 sandbox execution over the neutral ExecutionStore."""

import multiprocessing
import time
from datetime import datetime, timezone
from pathlib import Path

from anima.agent.executor import (
    SandboxHandler,
    SandboxToolError,
    build_sandbox_handlers,
)
from anima.agent.tools import ToolOutputError, ToolRegistry
from .contracts import ExecutionAction, ExecutionReceipt, thaw
from .store import ExecutionStore, action_request_hash, operation_kind


class ExecutionRejectedError(RuntimeError):
    """Execution intent is not safely bound to the persisted operation ledger."""


class UncertainOperationError(RuntimeError):
    """An ambiguous prior side effect cannot be safely reconciled."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _worker_entry(handler, root, arguments, operation_id, send_connection):
    try:
        try:
            output = handler(root, arguments, operation_id)
        except BaseException as error:
            code = getattr(error, "code", "EXECUTION_ERROR")
            message = getattr(error, "message", f"{type(error).__name__}: {error}")
            effect_possible = bool(getattr(error, "effect_possible", True))
            result = {
                "kind": "tool_error" if hasattr(error, "code") else "system_error",
                "code": code,
                "message": message,
                "effect_possible": effect_possible,
            }
        else:
            result = {"kind": "success", "output": output}
        send_connection.send(result)
    finally:
        send_connection.close()


class SandboxExecutor:
    """Execute trusted handlers without AgentRun/AgentStep ownership."""

    def __init__(self, *, root, registry, store, handlers=None):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("SandboxExecutor registry must be ToolRegistry")
        if not isinstance(store, ExecutionStore):
            raise TypeError("SandboxExecutor store must be ExecutionStore")
        root = Path(root).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("SandboxExecutor root must be an existing directory")
        selected = build_sandbox_handlers() if handlers is None else dict(handlers)
        for key, handler in selected.items():
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
        self.handlers = selected

    def _validate_binding(self, action, descriptor, operation):
        if operation is None:
            raise ExecutionRejectedError(
                "ExecutionAction requires a persisted ExecutionOperation"
            )
        expected = {
            "task_id": action.persistent_task_id,
            "goal_id": action.goal_id,
            "action_id": action.public_id,
            "candidate_id": action.candidate_id,
            "operation_kind": operation_kind(action),
            "request_hash": action_request_hash(action),
            "idempotency_class": descriptor.idempotency,
        }
        for field, value in expected.items():
            if operation[field] != value:
                raise ExecutionRejectedError(
                    f"ExecutionOperation {field} does not match ExecutionAction"
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

    def _run_worker(self, action, descriptor, handler):
        methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
        receive_connection, send_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker_entry,
            args=(
                handler.execute,
                str(self.root),
                thaw(action.arguments),
                action.operation_id,
                send_connection,
            ),
        )
        process.daemon = True
        started_at = _now()
        try:
            process.start()
        except BaseException as error:
            send_connection.close()
            receive_connection.close()
            return started_at, {
                "kind": "system_error",
                "code": "WORKER_START_FAILED",
                "message": str(error),
                "effect_possible": False,
            }
        send_connection.close()
        deadline = time.monotonic() + descriptor.timeout_seconds
        remaining = max(0.0, deadline - time.monotonic())
        if not receive_connection.poll(remaining):
            alive = process.is_alive()
            if alive:
                process.terminate()
            process.join()
            receive_connection.close()
            return started_at, {
                "kind": "timeout" if alive else "system_error",
                "code": "TIMEOUT" if alive else "WORKER_EXIT",
                "message": (
                    f"tool exceeded {descriptor.timeout_seconds:g}s timeout"
                    if alive
                    else f"worker exited with code {process.exitcode}"
                ),
                "effect_possible": descriptor.effect_class != "read_only",
            }
        try:
            result = receive_connection.recv()
        except EOFError:
            result = {
                "kind": "system_error",
                "code": "WORKER_EXIT",
                "message": "worker connection closed without a result",
                "effect_possible": descriptor.effect_class != "read_only",
            }
        finally:
            receive_connection.close()
        remaining = max(0.0, deadline - time.monotonic())
        process.join(remaining)
        if process.is_alive():
            process.terminate()
            process.join()
        return started_at, result

    def _invoke(self, action, descriptor, handler, *, mutate_operation=True):
        started_at, result = self._run_worker(action, descriptor, handler)
        kind = result.get("kind")
        if kind == "timeout":
            if mutate_operation:
                self._mark_after_failure(
                    action,
                    descriptor,
                    reason="tool execution timed out",
                    effect_possible=bool(result.get("effect_possible")),
                )
            return self._receipt(
                action,
                status="timeout",
                started_at=started_at,
                code=result["code"],
                message=result["message"],
            )
        if kind != "success":
            if mutate_operation:
                self._mark_after_failure(
                    action,
                    descriptor,
                    reason=result.get("message", "worker error"),
                    effect_possible=bool(result.get("effect_possible")),
                )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code=result.get("code", "EXECUTION_ERROR"),
                message=result.get("message", "worker error"),
            )
        output = result.get("output")
        try:
            descriptor.validate_output(output)
        except ToolOutputError as error:
            if mutate_operation:
                self._mark_after_failure(
                    action,
                    descriptor,
                    reason=f"invalid tool output: {error}",
                    effect_possible=descriptor.effect_class != "read_only",
                )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code="INVALID_TOOL_OUTPUT",
                message=str(error),
            )
        if mutate_operation:
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
        if not isinstance(action, ExecutionAction):
            raise TypeError("SandboxExecutor.execute() requires ExecutionAction")
        descriptor = self.registry.get(action.tool, action.tool_version)
        descriptor.validate_input(thaw(action.arguments))
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
                    thaw(action.arguments),
                    action.operation_id,
                )
                descriptor.validate_output(output)
                return self._receipt(
                    action,
                    status="succeeded",
                    started_at=started_at,
                    output=output,
                )
            if descriptor.idempotency == "repeat_safe":
                return self._invoke(
                    action,
                    descriptor,
                    handler,
                    mutate_operation=False,
                )
            raise ExecutionRejectedError(
                "Completed operation has no deterministic safe replay"
            )

        if status in {"failed", "cancelled"}:
            raise ExecutionRejectedError(
                f"Terminal ExecutionOperation cannot execute again: {status}"
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
                        thaw(action.arguments),
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
                    return self._receipt(
                        action,
                        status="succeeded",
                        started_at=_now(),
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
            raise ExecutionRejectedError(
                f"Unsupported ExecutionOperation state: {status}"
            )
        return self._invoke(action, descriptor, handler)


__all__ = [
    "ExecutionRejectedError",
    "SandboxExecutor",
    "UncertainOperationError",
]
