import json
from pathlib import Path


class EventLog:
    def __init__(self, log_file="data/events.jsonl"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event):
        with self.log_file.open("a", encoding="utf-8") as file:
            json.dump(
                event.to_dict(),
                file,
                ensure_ascii=False,
            )
            file.write("\n")
