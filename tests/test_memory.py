import json

import pytest

from anima.memory.episodic import EpisodicMemory
from anima.memory.memory_store import MemoryStore


def test_memory_store_writes_and_memory_reads(tmp_path):
    memory_file = tmp_path / "memories.jsonl"

    store = MemoryStore(memory_file)
    memory = EpisodicMemory(memory_file)

    record = {
        "source": "conversation.user",
        "timestamp": "2026-10-26T12:00:00+00:00",
        "content": {
            "text": "hello",
        },
    }

    store.write(record)

    loaded = memory.load_memories()

    assert loaded == [record]
    assert memory.count() == 1
    assert memory.last() == [record]


def test_memory_store_rejects_invalid_record(tmp_path):
    memory_file = tmp_path / "memories.jsonl"
    store = MemoryStore(memory_file)

    invalid = {
        "source": "conversation.user",
    }

    with pytest.raises(ValueError):
        store.write(invalid)


def test_memory_reports_malformed_line(tmp_path):
    memory_file = tmp_path / "memories.jsonl"

    memory_file.write_text(
        '{"source":"conversation.user",'
        '"timestamp":"2026-10-26T12:00:00+00:00",'
        '"content":{"text":"hello"}}\n'
        '{"source":\n',
        encoding="utf-8",
    )

    memory = EpisodicMemory(memory_file)

    with pytest.raises(
        ValueError,
        match="line 2: malformed JSON",
    ):
        memory.load_memories()


def test_memory_reports_invalid_record_with_line_number(
    tmp_path,
):
    memory_file = tmp_path / "memories.jsonl"

    memory_file.write_text(
        json.dumps(
            {
                "source": "conversation.user",
                "timestamp": "2026-10-26T12:00:00+00:00",
                "content": {
                    "text": 123,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    memory = EpisodicMemory(memory_file)

    with pytest.raises(ValueError) as error:
        memory.load_memories()

    assert "line 1" in str(error.value)
