import json
from pathlib import Path


MEMORY_SOURCE = "conversation.user"


def validate_memory_record(memory):
    if not isinstance(memory, dict):
        raise ValueError("Memory record must be an object")

    required_fields = {
        "source",
        "timestamp",
        "content",
    }

    missing_fields = required_fields - memory.keys()

    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(
            f"Memory record missing fields: {missing}"
        )

    if memory["source"] != MEMORY_SOURCE:
        raise ValueError(
            f"Memory record 'source' must be {MEMORY_SOURCE!r}"
        )

    if (
        not isinstance(memory["timestamp"], str)
        or not memory["timestamp"]
    ):
        raise ValueError(
            "Memory record 'timestamp' must be a non-empty string"
        )

    content = memory["content"]

    if not isinstance(content, dict):
        raise ValueError(
            "Memory record 'content' must be an object"
        )

    if "text" not in content:
        raise ValueError(
            "Memory record 'content' must contain 'text'"
        )

    if not isinstance(content["text"], str):
        raise ValueError(
            "Memory record 'content.text' must be a string"
        )

    return memory


class MemoryStore:
    def __init__(self, memory_file="data/memories.jsonl"):
        self.memory_file = Path(memory_file)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, memory):
        validate_memory_record(memory)

        with self.memory_file.open("a", encoding="utf-8") as file:
            json.dump(
                memory,
                file,
                ensure_ascii=False,
            )
            file.write("\n")
