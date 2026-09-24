import json
from pathlib import Path


class EpisodicMemory:
    def __init__(self, log_file="data/events.jsonl"):
        self.log_file = Path(log_file)

    def load_events(self):
        if not self.log_file.exists():
            return []

        events = []

        with self.log_file.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not line:
                    continue

                events.append(json.loads(line))

        return events

    def count(self):
        return len(self.load_events())

    def last(self, limit=5):
        events = self.load_events()
        return events[-limit:]
