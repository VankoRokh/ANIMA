import resource
import time


class DiagnosticMetrics:
    """Collect lightweight timing and process resource metrics."""

    def __init__(self):
        self._timings = []

    def measure(self, name, operation):
        if not isinstance(name, str):
            raise ValueError(
                "Metric name must be a string"
            )

        if not name.strip():
            raise ValueError(
                "Metric name must not be empty"
            )

        if not callable(operation):
            raise ValueError(
                "Measured operation must be callable"
            )

        started = time.perf_counter()

        result = operation()

        duration = time.perf_counter() - started

        self._timings.append(
            {
                "name": name,
                "duration_seconds": duration,
            }
        )

        return result

    def timings(self):
        return [
            timing.copy()
            for timing in self._timings
        ]

    def resources(self):
        usage = resource.getrusage(
            resource.RUSAGE_SELF
        )

        return {
            "cpu_user_seconds": usage.ru_utime,
            "cpu_system_seconds": usage.ru_stime,
            "max_rss_kb": usage.ru_maxrss,
        }

    def snapshot(self):
        return {
            "timings": self.timings(),
            "resources": self.resources(),
        }

    def clear(self):
        self._timings.clear()
