import json
import os
import subprocess
import sys
from pathlib import Path

from tests.harness import AnimaTestHarness


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def run_cli_session(data_dir, text):
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


def test_d1_cli_and_headless_are_equivalent(
    tmp_path,
):
    headless_dir = tmp_path / "headless"
    cli_dir = tmp_path / "cli"

    headless = AnimaTestHarness(headless_dir)

    scenario_result = headless.run_scenario(
        [
            {"action": "wake"},
            {
                "action": "user_input",
                "text": "D1 validation",
            },
            {"action": "sleep"},
        ]
    )

    headless_snapshot = headless.snapshot()

    run_cli_session(
        cli_dir,
        "D1 validation",
    )

    cli_state = json.loads(
        (
            cli_dir / "state.json"
        ).read_text(encoding="utf-8")
    )

    headless_events = read_jsonl(
        headless_dir / "events.jsonl"
    )

    cli_events = read_jsonl(
        cli_dir / "events.jsonl"
    )

    headless_memory = read_jsonl(
        headless_dir / "memories.jsonl"
    )

    cli_memory = read_jsonl(
        cli_dir / "memories.jsonl"
    )

    assert scenario_result == [
        {
            "action": "wake",
            "events": ["system.wake"],
        },
        {
            "action": "user_input",
            "events": ["conversation.user"],
        },
        {
            "action": "sleep",
            "events": ["system.sleep"],
        },
    ]

    assert headless_snapshot["state"]["status"] == "sleeping"
    assert cli_state["status"] == "sleeping"

    assert headless_snapshot["state"]["session"] == 1
    assert cli_state["session"] == 1

    assert (
        headless_snapshot["state"]["events_processed"]
        == cli_state["events_processed"]
        == 3
    )

    assert [
        event["type"]
        for event in headless_events
    ] == [
        event["type"]
        for event in cli_events
    ] == [
        "system.wake",
        "conversation.user",
        "system.sleep",
    ]

    assert [
        event["source"]
        for event in headless_events
    ] == [
        event["source"]
        for event in cli_events
    ] == [
        "runtime",
        "user",
        "runtime",
    ]

    assert {
        event["session_id"]
        for event in headless_events
    } == {"session_00000001"}
    assert {
        event["session_id"]
        for event in cli_events
    } == {"session_00000001"}

    assert len({
        event["id"]
        for event in headless_events
    }) == 3
    assert len({
        event["id"]
        for event in cli_events
    }) == 3

    assert len(headless_memory) == 1
    assert len(cli_memory) == 1

    assert (
        headless_memory[0]["content"]["text"]
        == cli_memory[0]["content"]["text"]
        == "D1 validation"
    )

    trace = headless.trace.lines()

    print("\nD1 diagnostic trace:")
    for line in trace:
        print(line)

    print("\nD1 metrics:")
    print(
        json.dumps(
            headless.metrics.snapshot(),
            indent=2,
        )
    )
