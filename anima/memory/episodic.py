import json
from pathlib import Path

from anima.memory.memory_store import validate_memory_record


class EpisodicMemory:
    def __init__(self, memory_file="data/memories.jsonl"):
        self.memory_file = Path(memory_file)

    def load_memories(self):
        if not self.memory_file.exists():
            return []

        memories = []

        with self.memory_file.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()

                if not line:
                    continue

                try:
                    memory = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Invalid memory store {self.memory_file}, "
                        f"line {line_number}: malformed JSON"
                    ) from error

                try:
                    validate_memory_record(memory)
                except ValueError as error:
                    raise ValueError(
                        f"Invalid memory store {self.memory_file}, "
                        f"line {line_number}: {error}"
                    ) from error

                memories.append(memory)

        return memories

    def count(self):
        return len(self.load_memories())

    def last(self, limit=5):
        memories = self.load_memories()
        return memories[-limit:]
