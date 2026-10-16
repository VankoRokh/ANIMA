import tempfile

from tests.harness import AnimaTestHarness


def test_runtime_headless_lifecycle():
    with tempfile.TemporaryDirectory(
        prefix="anima-runtime-test-"
    ) as temp_dir:
        anima = AnimaTestHarness(temp_dir)

        wake_events = anima.runtime.wake()
        input_events = anima.runtime.user_input(
            "pytest runtime"
        )
        sleep_events = anima.runtime.sleep()

        assert [
            event.event_type
            for event in wake_events
        ] == ["wake"]

        assert [
            event.event_type
            for event in input_events
        ] == ["user_input"]

        assert [
            event.event_type
            for event in sleep_events
        ] == ["sleep"]

        snapshot = anima.snapshot()

        assert snapshot["state"]["status"] == "sleeping"
        assert snapshot["state"]["session"] == 1
        assert snapshot["state"]["events_processed"] == 3
        assert snapshot["memory"]["count"] == 1


def test_runtime_snapshot_preserves_identity():
    with tempfile.TemporaryDirectory(
        prefix="anima-snapshot-test-"
    ) as temp_dir:
        anima = AnimaTestHarness(temp_dir)

        initial = anima.snapshot()

        instance_id = initial["identity"]["instance_id"]

        anima.runtime.wake()
        anima.runtime.user_input(
            "snapshot pytest"
        )
        anima.runtime.sleep()

        final = anima.snapshot()

        assert final["identity"]["instance_id"] == instance_id
        assert final["state"]["status"] == "sleeping"
        assert final["state"]["events_processed"] == 3
        assert final["memory"]["count"] == 1
