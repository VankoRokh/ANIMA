from pathlib import Path

from anima.cognition.routing import CognitiveDestination, CognitiveRouter
from anima.resolution import ResolutionRoute, resolve
from scripts.run_stage6_deep_smoke import (
    DEFAULT_MODEL_LABEL,
    deep_conflict_task,
    parse_args,
)


def test_deep_smoke_scenario_requires_deep_before_any_model_call():
    task = deep_conflict_task()
    resolution = resolve(task)
    decision = CognitiveRouter().route(task, resolution)

    assert resolution.route == ResolutionRoute.COGNITIVE_REQUIRED
    assert resolution.reason == "conflicting_or_multiple_facts"
    assert decision.destination == CognitiveDestination.DEEP
    assert task.raw_input is not None


def test_deep_smoke_defaults_to_smollm3_but_cli_can_replace_model():
    defaults = parse_args([])
    assert defaults.model_label == DEFAULT_MODEL_LABEL == "SmolLM3-3B-Q8_0"

    custom = parse_args([
        "--model", "/tmp/other.gguf",
        "--model-label", "Other-Model",
        "--port", "9012",
    ])
    assert custom.model == Path("/tmp/other.gguf")
    assert custom.model_label == "Other-Model"
    assert custom.port == 9012
