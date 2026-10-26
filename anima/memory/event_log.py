import json
from pathlib import Path

from anima.core.event_bus import Event


class EventLog:
    def __init__(self, log_file="data/events.jsonl"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._known_ids = None

    def _load_known_ids(self):
        if self._known_ids is None:
            self._known_ids = {
                record["id"]
                for record in self.load_events()
            }

        return self._known_ids

    def write(self, event):
        if not isinstance(event, Event):
            raise ValueError(
                "EventLog.write() requires an Event"
            )

        record = event.to_dict()
        Event.validate_record(record)

        known_ids = self._load_known_ids()

        if record["id"] in known_ids:
            raise ValueError(
                f"Duplicate event id: {record['id']}"
            )

        with self.log_file.open(
            "a",
            encoding="utf-8",
        ) as file:
            json.dump(
                record,
                file,
                ensure_ascii=False,
                allow_nan=False,
            )
            file.write("\n")

        known_ids.add(record["id"])

    def load_events(self):
        if not self.log_file.exists():
            return []

        events = []
        seen_ids = set()

        with self.log_file.open(
            "r",
            encoding="utf-8",
        ) as file:
            for line_number, line in enumerate(
                file,
                start=1,
            ):
                line = line.strip()

                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Invalid event log {self.log_file}, "
                        f"line {line_number}: malformed JSON"
                    ) from error

                try:
                    Event.validate_record(record)
                except ValueError as error:
                    raise ValueError(
                        f"Invalid event log {self.log_file}, "
                        f"line {line_number}: {error}"
                    ) from error

                event_id = record["id"]

                if event_id in seen_ids:
                    raise ValueError(
                        f"Invalid event log {self.log_file}, "
                        f"line {line_number}: "
                        f"duplicate event id {event_id}"
                    )

                seen_ids.add(event_id)
                events.append(record)

        if self._known_ids is not None:
            self._known_ids = set(seen_ids)

        return events
