import tempfile

import pytest

from anima.scenario import ScenarioRunner
from tests.harness import AnimaTestHarness


def test_scenario_runner_executes_headless_scenario():
    with tempfile.TemporaryDirectory(
        prefix="anima-scenario-test-"
    ) as temp_dir:
        anima = AnimaTestHarness(temp_dir)

        result = anima.run_scenario([
            {"action": "wake"},
            {
                "action": "user_input",
                "text": "scenario pytest",
            },
            {"action": "sleep"},
        ])

        assert result == [
            {
                "action": "wake",
                "events": ["wake"],
            },
            {
                "action": "user_input",
                "events": ["user_input"],
            },
            {
                "action": "sleep",
                "events": ["sleep"],
            },
        ]

        snapshot = anima.snapshot()

        assert snapshot["state"]["status"] == "sleeping"
        assert snapshot["state"]["session"] == 1
        assert snapshot["state"]["events_processed"] == 3
        assert snapshot["memory"]["count"] == 1


class DummyRuntime:
    def wake(self):
        return []

    def user_input(self, text):
        return []

    def sleep(self):
        return []


@pytest.mark.parametrize(
    ("scenario", "expected_message"),
    [
        (
            None,
            "Scenario must be a list of steps",
        ),
        (
            [],
            "Scenario must contain at least one step",
        ),
        (
            [
                {"action": "wake"},
                {"action": "unknown"},
            ],
            "Scenario step 1: Unknown scenario action: 'unknown'",
        ),
    ],
)
def test_scenario_runner_rejects_invalid_scenarios(
    scenario,
    expected_message,
):
    runner = ScenarioRunner(DummyRuntime())

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        runner.run(scenario)
