import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from anima.memory.memory_store import MemoryStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def run_session(data_dir, text):
    env = dict(
        os.environ,
        ANIMA_DATA_DIR=str(data_dir),
        PYTHONDONTWRITEBYTECODE="1",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(PROJECT_ROOT / "main.py"),
        ],
        cwd=PROJECT_ROOT,
        input=text + "\n\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr


def test_backup_recovery_preserves_history_and_memory(
    tmp_path,
):
    original = tmp_path / "original"
    restored_root = tmp_path / "restored"
    restored = restored_root / "data"

    # Первая полноценная сессия.
    run_session(
        original,
        "Проверка ANIMA",
    )

    first_state = json.loads(
        (original / "state.json").read_text(
            encoding="utf-8"
        )
    )

    assert first_state["session"] == 1
    assert first_state["status"] == "sleeping"
    assert first_state["events_processed"] == 3
    assert (original / "memory.db").exists()
    assert not (original / "memories.jsonl").exists()

    first_store = MemoryStore(original / "memory.db")
    first_memories = first_store.list_memories()
    assert len(first_memories) == 1
    assert first_memories[0]["content"] == "Проверка ANIMA"

    # Создаём резервную копию каталога данных.
    backup = tmp_path / "instance.tar.gz"

    with tarfile.open(backup, "w:gz") as archive:
        archive.add(
            original,
            arcname="data",
        )

    # Восстанавливаем данные в новое место.
    restored_root.mkdir()

    with tarfile.open(backup, "r:gz") as archive:
        archive.extractall(
            restored_root,
            filter="data",
        )

    # До нового запуска восстановленные данные
    # должны быть идентичны исходным.
    for path in original.iterdir():
        restored_path = restored / path.name

        assert restored_path.exists()
        assert path.read_bytes() == restored_path.read_bytes()

    # Вторая сессия после восстановления.
    # Пробелы не должны попасть в selected memory.
    run_session(
        restored,
        "   ",
    )

    final_state = json.loads(
        (restored / "state.json").read_text(
            encoding="utf-8"
        )
    )

    events = read_jsonl(
        restored / "events.jsonl"
    )

    restored_store = MemoryStore(restored / "memory.db")
    memories = restored_store.list_memories()

    assert final_state["session"] == 2
    assert final_state["status"] == "sleeping"
    assert final_state["events_processed"] == 6

    assert len(events) == 6

    assert [
        event["type"]
        for event in events
    ] == [
        "system.wake",
        "conversation.user",
        "system.sleep",
        "system.wake",
        "conversation.user",
        "system.sleep",
    ]

    assert [
        event["session_id"]
        for event in events
    ] == [
        "session_00000001",
        "session_00000001",
        "session_00000001",
        "session_00000002",
        "session_00000002",
        "session_00000002",
    ]

    assert len({event["id"] for event in events}) == 6

    # В raw event history сохраняются обе сессии,
    # включая второй пустой conversation.user.
    user_inputs = [
        event
        for event in events
        if event["type"] == "conversation.user"
    ]

    assert len(user_inputs) == 2

    # А SQLite memory содержит только содержательный ввод первой сессии.
    assert len(memories) == 1
    assert memories[0]["content"] == "Проверка ANIMA"
    assert memories[0]["type"] == "episodic"
    assert memories[0]["domain"] == "user"
    assert restored_store.source_events(
        memories[0]["id"]
    ) == [user_inputs[0]["id"]]
