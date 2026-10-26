from anima.interfaces.cli import run_cli
from tests.harness import AnimaTestHarness


def test_eof_interrupt_finishes_session_sleeping(
    tmp_path,
    monkeypatch,
):
    anima = AnimaTestHarness(tmp_path)

    def raise_eof(prompt):
        raise EOFError

    monkeypatch.setattr(
        "builtins.input",
        raise_eof,
    )

    run_cli(
        runtime=anima.runtime,
        anima=anima.state,
        identity=anima.identity,
        memory=anima.memory,
    )

    snapshot = anima.snapshot()

    assert snapshot["state"]["status"] == "sleeping"
    assert snapshot["state"]["session"] == 1
    assert snapshot["state"]["events_processed"] == 2
    assert snapshot["memory"]["count"] == 0


def test_keyboard_interrupt_after_input_preserves_input(
    tmp_path,
    monkeypatch,
):
    anima = AnimaTestHarness(tmp_path)

    responses = iter(
        [
            "important input",
            KeyboardInterrupt(),
        ]
    )

    def fake_input(prompt):
        result = next(responses)

        if isinstance(result, BaseException):
            raise result

        return result

    monkeypatch.setattr(
        "builtins.input",
        fake_input,
    )

    run_cli(
        runtime=anima.runtime,
        anima=anima.state,
        identity=anima.identity,
        memory=anima.memory,
    )

    snapshot = anima.snapshot()

    assert snapshot["state"]["status"] == "sleeping"
    assert snapshot["state"]["session"] == 1
    assert snapshot["state"]["events_processed"] == 3
    assert snapshot["memory"]["count"] == 1

    memories = anima.memory.load_memories()

    assert memories[0]["content"] == "important input"
    assert memories[0]["type"] == "episodic"
    assert memories[0]["domain"] == "user"
