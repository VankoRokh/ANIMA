import json
from pathlib import Path


class MemoryStore:
    def __init__(self, memory_file="data/memories.jsonl"):
        self.memory_file = Path(memory_file)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, memory):
        with self.memory_file.open("a", encoding="utf-8") as file:
            json.dump(
                memory,
                file,
                ensure_ascii=False,
            )
            file.write("\n")
