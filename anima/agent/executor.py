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

    def _invoke(self, action, descriptor, handler):
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

        deadline = time.monotonic() + descriptor.timeout_seconds
        remaining = max(0.0, deadline - time.monotonic())
        if not receive_connection.poll(remaining):
            alive = process.is_alive()
            if alive:
                process.terminate()
            process.join()
            receive_connection.close()
            if alive:
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

        try:
            result = receive_connection.recv()
        except EOFError:
            result = None
        finally:
            receive_connection.close()

        remaining = max(0.0, deadline - time.monotonic())
        process.join(remaining)
        if process.is_alive():
            process.terminate()
            process.join()

        if result is None:
            effect_possible = descriptor.effect_class != "read_only"
            self._mark_after_failure(
                action,
                descriptor,
                reason="worker connection closed without a result",
                effect_possible=effect_possible,
            )
            return self._receipt(
                action,
                status="failed",
                started_at=started_at,
                code="WORKER_EXIT",
                message=f"worker exited with code {process.exitcode}",
            )

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
        if isinstance(action, Action):
            descriptor = self.registry.get(action.tool, action.tool_version)
            descriptor.validate_input(action.to_dict()["arguments"])
            handler = self.handlers.get((action.tool, action.tool_version))
            if handler is not None:
                operation = self.store.get_operation(action.operation_id)
                if operation is not None and operation["status"] == "succeeded":
                    self._validate_binding(action, descriptor, operation)
                    if descriptor.idempotency == "repeat_safe":
                        raise ExecutionRejectedError(
                            "repeat-safe completed operation requires a new AgentOperation in Stage 4.4"
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
