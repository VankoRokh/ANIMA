"""Measure the Stage 4.12 small-model prompt profile without calling a model.

This is intentionally tokenizer-independent: it reports exact serialized character
counts and compares the compact projection with the full Planner prompt. Actual
model token counts are measured later by the live inference endpoint.
"""

import json
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.agent import (
    SMALL_LLM_MAX_OUTPUT_TOKENS,
    SMALL_LLM_MAX_PROMPT_CHARS,
    PlannerRequest,
    SmallLLMPromptProfile,
    build_llm_planner_prompts,
    build_sandbox_registry,
)


def _step(receipt_status, verification_outcome):
    return {
        "step_id": f"ast_{uuid4()}",
        "planner_turn_id": f"pt_{uuid4()}",
        "planner_status": "proposals_available",
        "selected_proposal_id": f"ap_{uuid4()}",
        "action_id": f"act_{uuid4()}",
        "receipt_status": receipt_status,
        "observation_id": f"obs_{uuid4()}",
        "verification_outcome": verification_outcome,
    }


def _observation(kind, data):
    return {
        "id": f"obs_{uuid4()}",
        "action_id": f"act_{uuid4()}",
        "receipt_id": f"er_{uuid4()}",
        "source": "sandbox_executor",
        "kind": kind,
        "data": data,
        "observed_at": "2026-10-28T00:00:00+00:00",
    }


def _request(*, steps=(), observations=()):
    return PlannerRequest(
        run_id=f"ar_{uuid4()}",
        step_id=f"ast_{uuid4()}",
        goal_id=f"goal_{uuid4()}",
        goal_description=(
            "Create result.txt containing exactly 42 in the allowed sandbox, "
            "then obtain independent readback evidence that the content is 42."
        ),
        success_criterion="result.txt content equals 42",
        context={},
        tools=build_sandbox_registry().list_descriptors(),
        recent_steps=tuple(steps),
        recent_observations=tuple(observations),
        constraints={"one_action_per_turn": True},
        remaining_budget={"steps": max(1, 6 - len(steps))},
    )


def _scenarios():
    missing = _observation(
        "file.unavailable",
        {
            "path": "missing-input.txt",
            "error_code": "NOT_FOUND",
            "message": "file does not exist: missing-input.txt",
        },
    )
    written = _observation(
        "file.write",
        {
            "path": "result.txt",
            "bytes_written": 2,
            "sha256": "a" * 64,
        },
    )
    return (
        ("turn-1", _request()),
        (
            "turn-2-after-failure",
            _request(
                steps=(_step("failed", "none"),),
                observations=(missing,),
            ),
        ),
        (
            "turn-3-after-write",
            _request(
                steps=(
                    _step("failed", "none"),
                    _step("succeeded", "none"),
                ),
                observations=(missing, written),
            ),
        ),
    )


def main():
    profile = SmallLLMPromptProfile()
    rows = []
    for label, request in _scenarios():
        full_system, full_user = build_llm_planner_prompts(request)
        compact_system, compact_user, metrics = profile.build(request)
        full_chars = len(full_system) + 1 + len(full_user)
        compact_chars = len(compact_system) + 1 + len(compact_user)
        rows.append(
            {
                "scenario": label,
                "full_prompt_chars": full_chars,
                "compact_prompt_chars": compact_chars,
                "saved_chars": full_chars - compact_chars,
                "reduction_percent": round(
                    100.0 * (full_chars - compact_chars) / full_chars,
                    1,
                ),
                "recent_steps_visible": metrics.recent_steps,
                "recent_observations_visible": metrics.recent_observations,
                "within_budget": compact_chars <= profile.max_prompt_chars,
            }
        )

    passed = all(row["within_budget"] for row in rows)
    print(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "note": (
                    "Character counts are exact; token counts depend on the selected "
                    "model tokenizer and are measured during live inference."
                ),
                "profile": {
                    "max_prompt_chars": SMALL_LLM_MAX_PROMPT_CHARS,
                    "max_output_tokens": SMALL_LLM_MAX_OUTPUT_TOKENS,
                    "max_tools": profile.max_tools,
                    "recent_steps": profile.recent_steps,
                    "recent_observations": profile.recent_observations,
                },
                "scenarios": rows,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
