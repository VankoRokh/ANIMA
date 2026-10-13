from datetime import datetime


EVENT_TYPES = {"wake", "user_input", "sleep"}


class Event:
    def __init__(self, event_type, payload=None):
        self._validate(event_type, payload)

        self.event_type = event_type
        self.payload = payload
        self.timestamp = datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _validate(event_type, payload):
        if not isinstance(event_type, str):
            raise ValueError("Event type must be a string")

        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event type: {event_type!r}"
            )

        if event_type in {"wake", "sleep"}:
            if payload is not None:
                raise ValueError(
                    f"Event {event_type!r} must have null payload"
                )

            return

        if event_type == "user_input":
            if not isinstance(payload, dict):
                raise ValueError(
                    "Event 'user_input' payload must be an object"
                )

            if "text" not in payload:
                raise ValueError(
                    "Event 'user_input' payload must contain 'text'"
                )

            if not isinstance(payload["text"], str):
                raise ValueError(
                    "Event 'user_input' payload 'text' must be a string"
                )

    @classmethod
    def validate_record(cls, record):
        if not isinstance(record, dict):
            raise ValueError("Event record must be an object")

        required_fields = {
            "type",
            "payload",
            "timestamp",
        }

        missing_fields = required_fields - record.keys()

        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(
                f"Event record missing fields: {missing}"
            )

        cls._validate(
            record["type"],
            record["payload"],
        )

        if (
            not isinstance(record["timestamp"], str)
            or not record["timestamp"]
        ):
            raise ValueError(
                "Event record 'timestamp' must be a non-empty string"
            )

        return record

    def to_dict(self):
        return {
            "type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class EventBus:
    def __init__(self):
        self.queue = []

    def emit(self, event_type, payload=None):
        event = Event(event_type, payload)
        self.queue.append(event)
        return event

    def has_events(self):
        return len(self.queue) > 0

    def next_event(self):
        if not self.queue:
            return None

        return self.queue.pop(0)
