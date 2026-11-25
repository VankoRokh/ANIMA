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
        self.input_usage_missing_calls = 0
        self.output_usage_missing_calls = 0
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
        a, b = (record.get("input_tokens"), record.get("output_tokens")) if type(record) is dict else (None, None)
        input_known = type(a) is int and a >= 0
        output_known = type(b) is int and b >= 0
        if input_known:
            self.input_tokens += a
        else:
            self.input_usage_missing_calls += 1
        if output_known:
            self.output_tokens += b
        else:
            self.output_usage_missing_calls += 1
        # Preserve the existing terminal reason for missing usage. Reported
        # counters are known subtotals, never estimates of unknown consumption.
        if not input_known or not output_known:
            self.reason = "USAGE_UNAVAILABLE"
            return self.reason
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
                "input_usage_missing_calls":self.input_usage_missing_calls,
                "output_usage_missing_calls":self.output_usage_missing_calls,
                "usage_complete":not (self.pending or self.input_usage_missing_calls
                                      or self.output_usage_missing_calls),
                "elapsed_ms":self._elapsed(),"stop_reason":self.reason,
                "reservation_pending":self.pending,
                "input_and_elapsed_boundary_only":True,
                "usage_backend_reported":True}
