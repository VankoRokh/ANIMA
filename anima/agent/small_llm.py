"""Compact Planner projection for small local language models.

The canonical PlannerRequest remains unchanged. This module only changes the
model-visible projection so small-context models are not forced to consume the
full internal Agent contract on every turn.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass

from anima.agent.llm_planner import (
    DEFAULT_LLM_TIMEOUT_SECONDS,
    LLMCallRecord,
    LLMCallResult,
    LLMPlanner,
    LLMPlannerError,
    LLMTransportError,
    MAX_LLM_CALL_HISTORY,
    OpenAICompatibleChatTransport,
    parse_llm_planner_decision,
)
from anima.agent.planner import PlannerRequest


SMALL_LLM_MAX_PROMPT_CHARS = 4_800
SMALL_LLM_MAX_TOOLS = 8
SMALL_LLM_RECENT_STEPS = 3
SMALL_LLM_RECENT_OBSERVATIONS = 3
SMALL_LLM_MAX_OUTPUT_TOKENS = 256
SMALL_LLM_CONTEXT_STRING_CHARS = 192
SMALL_LLM_OBSERVATION_STRING_CHARS = 384
SMALL_LLM_TOOL_DESCRIPTION_CHARS = 160


class SmallLLMPromptBudgetError(ValueError):
    """The compact model projection cannot fit the configured prompt budget."""


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _truncate_text(value, limit):
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    marker = "…[truncated]"
    keep = max(0, limit - len(marker))
    return value[:keep] + marker


def _compact_value(value, *, string_limit, list_limit=6, dict_limit=12):
    if isinstance(value, str):
        return _truncate_text(value, string_limit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result = {}
        items = list(value.items())
        for key, item in items[:dict_limit]:
            result[str(key)] = _compact_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
        if len(items) > dict_limit:
            result["_truncated_keys"] = len(items) - dict_limit
        return result
    if isinstance(value, (tuple, list)):
        items = list(value)
        result = [
            _compact_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in items[:list_limit]
        ]
        if len(items) > list_limit:
            result.append({"_truncated_items": len(items) - list_limit})
        return result
    return _truncate_text(str(value), string_limit)


def _compact_schema_property(name, schema, required):
    result = {
        "name": name,
        "type": schema.get("type", "unknown"),
        "required": name in required,
    }
    if "enum" in schema:
        result["enum"] = list(schema["enum"])
    if "maxLength" in schema:
        result["max_length"] = schema["maxLength"]
    return result


def _compact_tool(descriptor):
    record = descriptor.to_dict()
    input_schema = record["input_schema"]
    output_schema = record["output_schema"]
    required = set(input_schema.get("required", ()))
    arguments = [
        _compact_schema_property(name, schema, required)
        for name, schema in input_schema.get("properties", {}).items()
    ]
    returns = [
        {
            "name": name,
            "type": schema.get("type", "unknown"),
        }
        for name, schema in output_schema.get("properties", {}).items()
    ]
    return {
        "tool": descriptor.name,
        "version": descriptor.version,
        "description": _truncate_text(
            descriptor.description,
            SMALL_LLM_TOOL_DESCRIPTION_CHARS,
        ),
        "arguments": arguments,
        "effect": descriptor.effect_class,
        "returns": returns,
    }


def _compact_step(step):
    return {
        "planner_status": step.get("planner_status"),
        "receipt_status": step.get("receipt_status"),
        "verification_outcome": step.get("verification_outcome"),
    }


def _compact_observation(observation):
    data = observation.get("data", {})
    return {
        "kind": observation.get("kind"),
        "data": _compact_value(
            data,
            string_limit=SMALL_LLM_OBSERVATION_STRING_CHARS,
            list_limit=6,
            dict_limit=12,
        ),
    }


SMALL_LLM_SYSTEM_PROMPT = """You are ANIMA's proposal-only Planner.
Return one JSON object only. Do not use Markdown.
Choose only listed tools. You do not execute tools or decide safety, risk, effort,
success, goal completion, or internal state. Propose only the next action.
If information is missing, prefer a read/list action. Keep all summaries brief.
Output exactly: status, proposals, plan_summary.
Each proposal exactly: tool, tool_version, arguments, expected_observation,
rationale_summary. Use at most 3 proposals. Do not provide chain-of-thought."""


SMALL_LLM_RESPONSE_CONTRACT = {
    "status": "proposals_available|cannot_progress",
    "proposals": [
        {
            "tool": "listed tool name",
            "tool_version": "listed version",
            "arguments": {},
            "expected_observation": "brief factual expectation",
            "rationale_summary": "brief reason",
        }
    ],
    "plan_summary": "brief summary or null",
}


@dataclass(frozen=True, slots=True)
class SmallLLMPromptMetrics:
    system_chars: int
    user_chars: int
    total_chars: int
    tool_count: int
    recent_steps: int
    recent_observations: int

    def to_dict(self):
        return {
            "system_chars": self.system_chars,
            "user_chars": self.user_chars,
            "total_chars": self.total_chars,
            "tool_count": self.tool_count,
            "recent_steps": self.recent_steps,
            "recent_observations": self.recent_observations,
        }


@dataclass(frozen=True, slots=True)
class SmallLLMPromptProfile:
    max_prompt_chars: int = SMALL_LLM_MAX_PROMPT_CHARS
    max_tools: int = SMALL_LLM_MAX_TOOLS
    recent_steps: int = SMALL_LLM_RECENT_STEPS
    recent_observations: int = SMALL_LLM_RECENT_OBSERVATIONS

    def __post_init__(self):
        for name in ("max_prompt_chars", "max_tools", "recent_steps", "recent_observations"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"SmallLLMPromptProfile {name} must be a positive integer")

    def _payload(self, request, *, step_count=None, observation_count=None):
        if not isinstance(request, PlannerRequest):
            raise TypeError("SmallLLMPromptProfile requires a PlannerRequest")
        if len(request.tools) > self.max_tools:
            raise SmallLLMPromptBudgetError(
                f"small-model profile supports at most {self.max_tools} tools; "
                f"got {len(request.tools)}"
            )
        step_count = self.recent_steps if step_count is None else step_count
        observation_count = (
            self.recent_observations
            if observation_count is None
            else observation_count
        )
        return {
            "response_contract": SMALL_LLM_RESPONSE_CONTRACT,
            "goal": {
                "description": request.goal_description,
                "success_criterion": request.success_criterion,
            },
            "context": _compact_value(
                request.context,
                string_limit=SMALL_LLM_CONTEXT_STRING_CHARS,
                list_limit=4,
                dict_limit=12,
            ),
            "tools": [_compact_tool(tool) for tool in request.tools],
            "recent_steps": [
                _compact_step(item)
                for item in request.recent_steps[-step_count:]
            ],
            "recent_observations": [
                _compact_observation(item)
                for item in request.recent_observations[-observation_count:]
            ],
            "constraints": {
                "one_action_per_turn": True,
                "remaining_steps": request.remaining_budget.get("steps"),
            },
        }

    def build(self, request):
        step_count = min(self.recent_steps, len(request.recent_steps))
        observation_count = min(
            self.recent_observations,
            len(request.recent_observations),
        )

        while True:
            payload = self._payload(
                request,
                step_count=step_count,
                observation_count=observation_count,
            )
            user_prompt = _canonical_json(payload)
            system_prompt = SMALL_LLM_SYSTEM_PROMPT.strip()
            total_chars = len(system_prompt) + 1 + len(user_prompt)
            if total_chars <= self.max_prompt_chars:
                metrics = SmallLLMPromptMetrics(
                    system_chars=len(system_prompt),
                    user_chars=len(user_prompt),
                    total_chars=total_chars,
                    tool_count=len(request.tools),
                    recent_steps=step_count,
                    recent_observations=observation_count,
                )
                return system_prompt, user_prompt, metrics

            # Historical summaries are expendable before the latest factual observation.
            if step_count > 0:
                step_count -= 1
                continue
            if observation_count > 1:
                observation_count -= 1
                continue
            raise SmallLLMPromptBudgetError(
                f"compact Planner prompt is {total_chars} chars, exceeding "
                f"budget {self.max_prompt_chars}; reduce context/tools before model call"
            )


def build_small_llm_planner_prompts(request, profile=None):
    profile = profile or SmallLLMPromptProfile()
    system_prompt, user_prompt, _ = profile.build(request)
    return system_prompt, user_prompt


class SmallModelLLMPlanner(LLMPlanner):
    """LLMPlanner using a compact, bounded model-visible Planner projection."""

    def __init__(
        self,
        transport,
        *,
        profile=None,
        name="small-llm",
        version="1",
        timeout_seconds=DEFAULT_LLM_TIMEOUT_SECONDS,
    ):
        super().__init__(
            transport,
            name=name,
            version=version,
            timeout_seconds=timeout_seconds,
        )
        self.profile = profile or SmallLLMPromptProfile()
        if not isinstance(self.profile, SmallLLMPromptProfile):
            raise TypeError("SmallModelLLMPlanner profile must be SmallLLMPromptProfile")
        self._prompt_metrics = []

    @property
    def prompt_metrics(self):
        return tuple(self._prompt_metrics)

    def _decide(self, request):
        system_prompt, user_prompt, metrics = self.profile.build(request)
        result = self.transport.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(result, LLMCallResult):
            raise TypeError("LLMTransport.complete() must return LLMCallResult")
        decision = parse_llm_planner_decision(result.text)
        prompt_material = system_prompt + "\n" + user_prompt
        record = LLMCallRecord(
            provider=result.provider,
            model=result.model,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            finish_reason=result.finish_reason,
            prompt_hash=_sha256_text(prompt_material),
            response_hash=_sha256_text(result.text),
        )
        self._call_history.append(record)
        if len(self._call_history) > MAX_LLM_CALL_HISTORY:
            del self._call_history[:-MAX_LLM_CALL_HISTORY]
        self._prompt_metrics.append(metrics)
        if len(self._prompt_metrics) > MAX_LLM_CALL_HISTORY:
            del self._prompt_metrics[:-MAX_LLM_CALL_HISTORY]
        return decision


class SmallModelOpenAICompatibleChatTransport(OpenAICompatibleChatTransport):
    """OpenAI-compatible transport with an explicit short completion budget."""

    def __init__(self, *, max_output_tokens=SMALL_LLM_MAX_OUTPUT_TOKENS, **kwargs):
        if (
            not isinstance(max_output_tokens, int)
            or isinstance(max_output_tokens, bool)
            or max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        super().__init__(**kwargs)
        self.max_output_tokens = max_output_tokens

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("LLM system_prompt must be non-empty")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("LLM user_prompt must be non-empty")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("LLM timeout_seconds must be positive")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        if self.request_json_object:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self.extra_headers,
        }
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            self.endpoint,
            data=_canonical_json(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request,
                timeout=float(timeout_seconds),
            ) as response:
                raw = response.read(200_000)
        except urllib.error.HTTPError as error:
            try:
                detail = error.read(4096).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            message = f"LLM HTTP {error.code}"
            if detail.strip():
                message += ": " + detail.strip()
            raise LLMTransportError(message) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LLMTransportError(f"LLM transport failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000.0

        try:
            document = json.loads(raw.decode("utf-8"))
            choice = document["choices"][0]
            text = choice["message"]["content"]
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            raise LLMTransportError(
                "LLM endpoint returned an unsupported chat/completions response"
            ) from error
        if not isinstance(text, str) or not text.strip():
            raise LLMTransportError("LLM endpoint returned empty message content")

        usage = document.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool):
            input_tokens = None
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            output_tokens = None
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            finish_reason = str(finish_reason)

        return LLMCallResult(
            provider=self.provider,
            model=self.model,
            text=text,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=self._estimated_cost(input_tokens, output_tokens),
            finish_reason=finish_reason,
        )


__all__ = [
    "SMALL_LLM_MAX_OUTPUT_TOKENS",
    "SMALL_LLM_MAX_PROMPT_CHARS",
    "SMALL_LLM_MAX_TOOLS",
    "SMALL_LLM_RECENT_OBSERVATIONS",
    "SMALL_LLM_RECENT_STEPS",
    "SmallLLMPromptBudgetError",
    "SmallLLMPromptMetrics",
    "SmallLLMPromptProfile",
    "SmallModelLLMPlanner",
    "SmallModelOpenAICompatibleChatTransport",
    "build_small_llm_planner_prompts",
]
