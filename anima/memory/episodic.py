import json
from pathlib import Path


class EpisodicMemory:
    def __init__(self, memory_file="data/memories.jsonl"):
        self.memory_file = Path(memory_file)

    def load_memories(self):
        if not self.memory_file.exists():
            return []

        memories = []

        with self.memory_file.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not line:
                    continue

                memories.append(json.loads(line))

        return memories

    def count(self):
        return len(self.load_memories())

    def last(self, limit=5):
        memories = self.load_memories()
        return memories[-limit:]
