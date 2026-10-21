from datetime import datetime


class DiagnosticTrace:
    """Collect human-readable diagnostic runtime messages."""

    def __init__(self):
        self._entries = []

    def _now(self):
        return datetime.now().isoformat(
            timespec="milliseconds"
        )

    def record(self, message):
        if not isinstance(message, str):
            raise ValueError(
                "Trace message must be a string"
            )

        if not message.strip():
            raise ValueError(
                "Trace message must not be empty"
            )

        self._entries.append(
            {
                "timestamp": self._now(),
                "message": message,
            }
        )

    def entries(self):
        return [
            entry.copy()
            for entry in self._entries
        ]

    def lines(self):
        return [
            (
                f"[{entry['timestamp']}] "
                f"{entry['message']}"
            )
            for entry in self._entries
        ]

    def clear(self):
        self._entries.clear()
