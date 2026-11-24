"""Host-owned per-turn budget; no model or tool authority.

Output reservation uses the existing native max_tokens=256 request contract.
Input usage is reported by the backend after inference, and wall time is
checked at call boundaries. Neither is a hard in-flight resource ceiling.
"""
from dataclasses import dataclass, asdict
import time


@dataclass(frozen=True)
class ResourceLimits:
    max_calls: int = 4
    max_reported_input_tokens: int = 8192
    max_reported_output_tokens: int = 1024
    max_elapsed_ms: int = 60000

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise ValueError("positive integer resource limits required")


class ResourceBudget:
    OUTPUT_RESERVATION = 256

    def __init__(self, limits, *, clock=time.monotonic):
        if type(limits) is not ResourceLimits:
            raise TypeError("trusted ResourceLimits required")
        self.limits = limits
        self._clock = clock
        self._started = clock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.pending = False
        self.reason = None

    def _elapsed(self):
        return max(0, (self._clock() - self._started) * 1000)

    def check_next(self):
        if self.pending:
            raise ValueError("unresolved reservation")
        if self.reason is not None:
            return self.reason
        if self.calls >= self.limits.max_calls:
            return "MODEL_CALL_LIMIT"
        if self.output_tokens + self.OUTPUT_RESERVATION > self.limits.max_reported_output_tokens:
            return "OUTPUT_RESERVATION_LIMIT"
        if self.input_tokens >= self.limits.max_reported_input_tokens:
            return "INPUT_USAGE_LIMIT"
        if self._elapsed() >= self.limits.max_elapsed_ms:
            return "ELAPSED_LIMIT"
        return None

    def reserve(self):
        reason = self.check_next()
        if reason is not None:
            self.reason = reason
            return False
        self.calls += 1
        self.pending = True
        return True

    def settle(self, record):
        if not self.pending:
            raise ValueError("no model call reservation")
        self.pending = False
        if type(record) is not dict:
            self.reason = "USAGE_UNAVAILABLE"
            return self.reason
        a, b = record.get("input_tokens"), record.get("output_tokens")
        if type(a) is not int or type(b) is not int or a < 0 or b < 0:
            self.reason = "USAGE_UNAVAILABLE"
            return self.reason
        self.input_tokens += a
        self.output_tokens += b
        if b > self.OUTPUT_RESERVATION or self.output_tokens > self.limits.max_reported_output_tokens:
            self.reason = "OUTPUT_USAGE_EXCEEDED"
        elif self.input_tokens > self.limits.max_reported_input_tokens:
            self.reason = "INPUT_USAGE_EXCEEDED"
        elif self._elapsed() >= self.limits.max_elapsed_ms:
            self.reason = "ELAPSED_LIMIT"
        return self.reason

    def snapshot(self):
        return {"schema":"anima.lab.resource_budget/0.1",
                "limits":asdict(self.limits),"reserved_calls":self.calls,
                "reported_input_tokens":self.input_tokens,
                "reported_output_tokens":self.output_tokens,
                "elapsed_ms":self._elapsed(),"stop_reason":self.reason,
                "reservation_pending":self.pending,
                "input_and_elapsed_boundary_only":True,
                "usage_backend_reported":True}
