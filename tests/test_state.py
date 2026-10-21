import json

import pytest

from anima.core.state import AnimaState


def test_state_is_created_and_saved(tmp_path):
    state_file = tmp_path / "state.json"

    state = AnimaState(state_file)

    assert state_file.exists()

    saved = json.loads(
        state_file.read_text(encoding="utf-8")
    )

    assert saved["status"] == "created"
    assert saved["session"] == 0
    assert saved["events_processed"] == 0


def test_state_survives_reload(tmp_path):
    state_file = tmp_path / "state.json"

    state = AnimaState(state_file)
    state.wake()
    state.register_event()
    state.sleep()

    reloaded = AnimaState(state_file)

    assert reloaded.get()["status"] == "sleeping"
    assert reloaded.get()["session"] == 1
    assert reloaded.get()["events_processed"] == 1


def test_malformed_state_is_rejected_without_modifying_file(
    tmp_path,
):
    state_file = tmp_path / "state.json"

    state_file.write_text(
        '{"status":',
        encoding="utf-8",
    )

    original = state_file.read_bytes()

    with pytest.raises(
        ValueError,
        match="malformed JSON",
    ):
        AnimaState(state_file)

    assert state_file.read_bytes() == original


def test_incompatible_state_is_rejected_without_modifying_file(
    tmp_path,
):
    state_file = tmp_path / "state.json"

    state_file.write_text(
        json.dumps(
            {
                "name": "ANIMA",
                "version": "00.1-alpha",
                "status": "invalid-status",
                "session": 0,
                "created_at": "2026-10-16T12:00:00",
                "last_wake": None,
                "last_sleep": None,
                "events_processed": 0,
            }
        ),
        encoding="utf-8",
    )

    original = state_file.read_bytes()

    with pytest.raises(
        ValueError,
        match="unknown status",
    ):
        AnimaState(state_file)

    assert state_file.read_bytes() == original
