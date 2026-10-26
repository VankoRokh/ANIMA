import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4


EVENT_TYPE_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)
EVENT_ID_PREFIX = "ev_"


def _validate_json_value(value, label):
    try:
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{label} must be JSON-serializable"
        ) from error


class Event:
    def __init__(
        self,
        event_type,
        payload=None,
        *,
        source,
        session_id=None,
        references=None,
        event_id=None,
        timestamp=None,
    ):
        self.event_id = event_id or self._new_id()
        self.event_type = event_type
        self.payload = payload
        self.timestamp = timestamp or self._now()
        self.source = source
        self.session_id = session_id
        self.references = (
            list(references)
            if references is not None
            else []
        )

        self.validate_record(self.to_dict())

    @staticmethod
    def _new_id():
        return f"{EVENT_ID_PREFIX}{uuid4()}"

    @staticmethod
    def _now():
        return datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")

    @classmethod
    def _validate_id(cls, event_id):
        if (
            not isinstance(event_id, str)
            or not event_id.startswith(EVENT_ID_PREFIX)
        ):
            raise ValueError(
                "Event record 'id' must be an ev_ UUIDv4"
            )

        raw_uuid = event_id[len(EVENT_ID_PREFIX):]

        try:
            parsed = UUID(raw_uuid)
        except (ValueError, AttributeError) as error:
            raise ValueError(
                "Event record 'id' must be an ev_ UUIDv4"
            ) from error

        if (
            parsed.version != 4
            or str(parsed) != raw_uuid
        ):
            raise ValueError(
                "Event record 'id' must be an ev_ UUIDv4"
            )

    @staticmethod
    def _validate_type(event_type):
        if not isinstance(event_type, str):
            raise ValueError("Event type must be a string")

        if not EVENT_TYPE_PATTERN.fullmatch(event_type):
            raise ValueError(
                "Event type must be a hierarchical "
                "lowercase name such as 'system.wake'"
            )

    @staticmethod
    def _validate_payload(event_type, payload):
        if event_type in {"system.wake", "system.sleep"}:
            if payload is not None:
                raise ValueError(
                    f"Event {event_type!r} must have null payload"
                )
            return

        if event_type == "conversation.user":
            if not isinstance(payload, dict):
                raise ValueError(
                    "Event 'conversation.user' payload "
                    "must be an object"
                )

            if "text" not in payload:
                raise ValueError(
                    "Event 'conversation.user' payload "
                    "must contain 'text'"
                )

            if not isinstance(payload["text"], str):
                raise ValueError(
                    "Event 'conversation.user' payload "
                    "'text' must be a string"
                )

        _validate_json_value(
            payload,
            "Event payload",
        )

    @staticmethod
    def _validate_timestamp(timestamp):
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError(
                "Event record 'timestamp' "
                "must be a non-empty string"
            )

        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise ValueError(
                "Event record 'timestamp' "
                "must be ISO 8601"
            ) from error

        if (
            parsed.tzinfo is None
            or parsed.utcoffset() is None
        ):
            raise ValueError(
                "Event record 'timestamp' "
                "must include a UTC offset"
            )

    @staticmethod
    def _validate_source(source):
        if (
            not isinstance(source, str)
            or not source.strip()
        ):
            raise ValueError(
                "Event record 'source' "
                "must be a non-empty string"
            )

    @staticmethod
    def _validate_session_id(session_id):
        if session_id is None:
            return

        if (
            not isinstance(session_id, str)
            or not session_id.strip()
        ):
            raise ValueError(
                "Event record 'session_id' "
                "must be a non-empty string or null"
            )

    @staticmethod
    def _validate_references(references):
        if not isinstance(references, list):
            raise ValueError(
                "Event record 'references' must be a list"
            )

        for index, reference in enumerate(references):
            if not isinstance(reference, dict):
                raise ValueError(
                    f"Event reference {index} must be an object"
                )

            if set(reference) != {"kind", "id"}:
                raise ValueError(
                    f"Event reference {index} must contain "
                    "only 'kind' and 'id'"
                )

            for field in ("kind", "id"):
                value = reference[field]
                if (
                    not isinstance(value, str)
                    or not value.strip()
                ):
                    raise ValueError(
                        f"Event reference {index} '{field}' "
                        "must be a non-empty string"
                    )

    @classmethod
    def validate_record(cls, record):
        if not isinstance(record, dict):
            raise ValueError("Event record must be an object")

        required_fields = {
            "id",
            "type",
            "timestamp",
            "source",
            "session_id",
            "payload",
            "references",
        }

        missing_fields = required_fields - record.keys()
        unknown_fields = record.keys() - required_fields

        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(
                f"Event record missing fields: {missing}"
            )

        if unknown_fields:
            unknown = ", ".join(sorted(unknown_fields))
            raise ValueError(
                f"Event record unknown fields: {unknown}"
            )

        cls._validate_id(record["id"])
        cls._validate_type(record["type"])
        cls._validate_payload(
            record["type"],
            record["payload"],
        )
        cls._validate_timestamp(record["timestamp"])
        cls._validate_source(record["source"])
        cls._validate_session_id(record["session_id"])
        cls._validate_references(record["references"])

        return record

    def to_dict(self):
        return {
            "id": self.event_id,
            "type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "session_id": self.session_id,
            "payload": self.payload,
            "references": self.references,
        }


class EventBus:
    def __init__(self):
        self.queue = []

    def emit(
        self,
        event_type,
        payload=None,
        *,
        source,
        session_id=None,
        references=None,
    ):
        event = Event(
            event_type,
            payload,
            source=source,
            session_id=session_id,
            references=references,
        )
        self.queue.append(event)
        return event

    def has_events(self):
        return len(self.queue) > 0

    def next_event(self):
        if not self.queue:
            return None

        return self.queue.pop(0)
