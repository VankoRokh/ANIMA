import multiprocessing
import time

from anima.agent.contracts import Action
from anima.agent.tools import ToolOutputError
from . import _executor_impl as _impl
from ._executor_impl import (
    MAX_FILE_BYTES,
    MAX_LIST_ENTRIES,
    MAX_PATH_CHARS,
    STANDARD_TOOL_VERSION,
    ExecutionRejectedError,
    SandboxHandler,
    SandboxToolError,
    UncertainOperationError,
    action_request_hash,
    build_sandbox_registry,
    operation_kind,
    sandbox_tool_descriptors,
)


class SandboxExecutor(_impl.SandboxExecutor):
    """Public sandbox Executor with bounded worker IPC and recovery semantics."""

    def _run_worker(self, action, descriptor, handler):
        methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
        receive_connection, send_connection = context.Pipe(duplex=False)
        arguments = action.to_dict()["arguments"]
        process = context.Process(
            target=_impl._worker_entry,
            args=(handler.execute, str(self.root), arguments, action.operation_id, send_connection),
        )
        process.daemon = True
        started_at = _impl._now()
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
            if alive:
                return started_at, {
                    "kind": "timeout",
                    "code": "TIMEOUT",
                    "message": f"tool exceeded {descriptor.timeout_seconds:g}s timeout",
                    "effect_possible": descriptor.effect_class != "read_only",
                }
            return started_at, {
                "kind": "system_error",
                "code": "WORKER_EXIT",
                "message": f"worker exited with code {process.exitcode}",
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

        if kind == "tool_error":
            if mutate_operation:
                self._mark_after_failure(
                    action,
                    descriptor,
                    reason=f"tool error {result['code']}: {result['message']}",
                    effect_possible=bool(result.get("effect_possible")),
                )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code=result["code"],
                message=result["message"],
            )

        if kind != "success":
            if mutate_operation:
                self._mark_after_failure(
                    action,
                    descriptor,
                    reason=result.get("message", "worker system error"),
                    effect_possible=bool(result.get("effect_possible")),
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
        if isinstance(action, Action):
            descriptor = self.registry.get(action.tool, action.tool_version)
            descriptor.validate_input(action.to_dict()["arguments"])
            handler = self.handlers.get((action.tool, action.tool_version))
            if handler is not None:
                operation = self.store.get_operation(action.operation_id)
                if operation is not None and operation["status"] == "succeeded":
                    self._validate_binding(action, descriptor, operation)
                    if descriptor.idempotency == "repeat_safe":
                        return self._invoke(
                            action,
                            descriptor,
                            handler,
                            mutate_operation=False,
                        )
        return super().execute(action)


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_LIST_ENTRIES",
    "MAX_PATH_CHARS",
    "STANDARD_TOOL_VERSION",
    "ExecutionRejectedError",
    "SandboxExecutor",
    "SandboxHandler",
    "SandboxToolError",
    "UncertainOperationError",
    "action_request_hash",
    "build_sandbox_registry",
    "operation_kind",
    "sandbox_tool_descriptors",
]
