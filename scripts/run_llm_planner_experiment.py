"""Run the Stage 4.12 canonical Agent task against a real LLM endpoint.

The experiment uses a temporary ANIMA instance and sandbox. It does not touch the
normal data directory. The endpoint must expose an OpenAI-compatible
/chat/completions API.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anima.agent import (
    AgentStore,
    DeterministicGoalVerifier,
    GoalVerificationBridge,
    LLMPlanner,
    OpenAICompatibleChatTransport,
    ProposalChoiceCoordinator,
    RecoverableAgentLoop,
    SandboxExecutor,
    VerificationSpec,
    build_sandbox_registry,
)
from anima.agent.verification import (
    DETERMINISTIC_VERIFIER_NAME,
    DETERMINISTIC_VERIFIER_VERSION,
    FILE_CONTENT_EQUALS,
)
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore


def _optional_float(value):
    if value is None:
        return None
    return float(value)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run the Stage 4.12 canonical sandbox task with a real LLM Planner",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ANIMA_LLM_BASE_URL"),
        help="OpenAI-compatible base URL, e.g. http://localhost:11434/v1",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("ANIMA_LLM_MODEL"),
        help="Provider model identifier",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("ANIMA_LLM_PROVIDER", "openai-compatible"),
    )
    parser.add_argument(
        "--api-key-env",
        default="ANIMA_LLM_API_KEY",
        help="Environment variable containing the API key; omitted key is allowed",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument(
        "--input-cost-per-million",
        type=_optional_float,
        default=None,
        help="Optional USD per 1M input tokens; never guessed automatically",
    )
    parser.add_argument(
        "--output-cost-per-million",
        type=_optional_float,
        default=None,
        help="Optional USD per 1M output tokens; never guessed automatically",
    )
    parser.add_argument(
        "--no-response-format",
        action="store_true",
        help="Do not send response_format=json_object for endpoints that reject it",
    )
    return parser


def _sum_known(values):
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def run_experiment(args):
    if not args.base_url:
        raise ValueError("--base-url or ANIMA_LLM_BASE_URL is required")
    if not args.model:
        raise ValueError("--model or ANIMA_LLM_MODEL is required")
    if args.max_steps <= 0:
        raise ValueError("--max-steps must be positive")
    api_key = os.environ.get(args.api_key_env)

    transport = OpenAICompatibleChatTransport(
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        provider=args.provider,
        request_json_object=not args.no_response_format,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    planner = LLMPlanner(
        transport,
        name="llm-experiment",
        version="1",
        timeout_seconds=args.timeout,
    )

    with tempfile.TemporaryDirectory(prefix="anima-stage4-llm-") as temp:
        data_dir = Path(temp)
        sandbox = data_dir / "sandbox"
        sandbox.mkdir()
        agent_store = AgentStore(data_dir / "agent.db")
        internal = InternalStateRuntime(
            InternalStateStore(data_dir / "internal_state.db")
        )
        registry = build_sandbox_registry()
        choice = ProposalChoiceCoordinator(
            registry=registry,
            choice_engine=internal.choice_engine,
        )
        executor = SandboxExecutor(
            root=sandbox,
            registry=registry,
            store=agent_store,
        )
        verifier = DeterministicGoalVerifier()
        bridge = GoalVerificationBridge(
            agent_store=agent_store,
            recovery=internal.recovery,
        )
        loop = RecoverableAgentLoop(
            store=agent_store,
            registry=registry,
            planner=planner,
            choice=choice,
            executor=executor,
            verifier=verifier,
            verification_bridge=bridge,
        )

        goal = internal.create_goal(
            source="stage4.12-live-experiment",
            priority=1.0,
            description=(
                "Create result.txt containing exactly 42 in the allowed sandbox, "
                "then obtain independent readback evidence that the content is 42."
            ),
            success_criterion="result.txt content equals 42",
            reason="Stage 4.12 real LLM Planner experiment",
        )
        run = loop.start_run(goal["id"])
        spec = VerificationSpec.create(
            run_id=run["id"],
            verifier=DETERMINISTIC_VERIFIER_NAME,
            verifier_version=DETERMINISTIC_VERIFIER_VERSION,
            criterion_kind=FILE_CONTENT_EQUALS,
            parameters={"path": "result.txt", "expected": "42"},
        )
        result = loop.run(run["id"], spec, max_steps=args.max_steps)

        calls = [record.to_dict() for record in planner.call_history]
        output = {
            "provider": args.provider,
            "model": args.model,
            "completed": result.completed,
            "stop_reason": result.stop_reason,
            "run_status": result.run["status"],
            "goal_status": result.goal["status"],
            "turn_count": len(result.turns),
            "tool_calls": [
                turn.action.tool if turn.action is not None else None
                for turn in result.turns
            ],
            "receipt_statuses": [
                turn.receipt.status if turn.receipt is not None else None
                for turn in result.turns
            ],
            "verification_outcomes": [
                (
                    turn.verification_result.outcome
                    if turn.verification_result is not None
                    else None
                )
                for turn in result.turns
            ],
            "result_file_exists": (sandbox / "result.txt").exists(),
            "result_file_content": (
                (sandbox / "result.txt").read_text(encoding="utf-8")
                if (sandbox / "result.txt").is_file()
                else None
            ),
            "llm_calls": calls,
            "llm_totals": {
                "latency_ms": sum(record["latency_ms"] for record in calls),
                "input_tokens": _sum_known(
                    record["input_tokens"] for record in calls
                ),
                "output_tokens": _sum_known(
                    record["output_tokens"] for record in calls
                ),
                "estimated_cost_usd": _sum_known(
                    record["estimated_cost_usd"] for record in calls
                ),
            },
        }
        return output


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = run_experiment(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
