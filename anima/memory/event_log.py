import json
from pathlib import Path

from anima.core.event_bus import Event


class EventLog:
    def __init__(self, log_file="data/events.jsonl"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event):
        if not isinstance(event, Event):
            raise ValueError("EventLog.write() requires an Event")

        record = event.to_dict()
        Event.validate_record(record)

        with self.log_file.open("a", encoding="utf-8") as file:
            json.dump(
                record,
                file,
                ensure_ascii=False,
            )
            file.write("\n")

    def load_events(self):
        if not self.log_file.exists():
            return []

        events = []

        with self.log_file.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
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

                events.append(record)

        return events
