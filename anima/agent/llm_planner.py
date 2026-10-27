import hashlib
import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from anima.agent.planner import (
    MAX_PROPOSALS,
    PlannerAdapter,
    PlannerDecision,
    PlannerRequest,
    ProposalDraft,
)


MAX_LLM_RESPONSE_CHARS = 50_000
MAX_LLM_CALL_HISTORY = 64
DEFAULT_LLM_TIMEOUT_SECONDS = 60.0


class LLMPlannerError(ValueError):
    """The model response violates the ANIMA Planner contract."""


class LLMTransportError(RuntimeError):
    """The external model transport failed before a valid planner response existed."""


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_non_negative_int(value, label):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer or null")
    return value


def _optional_non_negative_number(value, label):
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{label} must be a non-negative number or null")
    return float(value)


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


def _require_exact_fields(record, expected, label):
    if not isinstance(record, dict):
        raise LLMPlannerError(f"{label} must be a JSON object")
    actual = set(record)
    expected = set(expected)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if extra:
        details.append("extra: " + ", ".join(extra))
    raise LLMPlannerError(
        f"{label} fields mismatch ({'; '.join(details)})"
    )


@dataclass(frozen=True, slots=True)
class LLMCallResult:
    provider: str
    model: str
    text: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    finish_reason: str | None = None

    def __post_init__(self):
        provider = _require_text(self.provider, "LLMCallResult provider")
        model = _require_text(self.model, "LLMCallResult model")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("LLMCallResult text must be non-empty")
        if len(self.text) > MAX_LLM_RESPONSE_CHARS:
            raise ValueError(
                f"LLMCallResult text exceeds {MAX_LLM_RESPONSE_CHARS} characters"
            )
        if (
            not isinstance(self.latency_ms, (int, float))
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ValueError("LLMCallResult latency_ms must be non-negative")
        input_tokens = _optional_non_negative_int(
            self.input_tokens,
            "LLMCallResult input_tokens",
        )
        output_tokens = _optional_non_negative_int(
            self.output_tokens,
            "LLMCallResult output_tokens",
        )
        cost = _optional_non_negative_number(
            self.estimated_cost_usd,
            "LLMCallResult estimated_cost_usd",
        )
        finish_reason = self.finish_reason
        if finish_reason is not None:
            finish_reason = _require_text(
                finish_reason,
                "LLMCallResult finish_reason",
            )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "text", self.text.strip())
        object.__setattr__(self, "latency_ms", float(self.latency_ms))
        object.__setattr__(self, "input_tokens", input_tokens)
        object.__setattr__(self, "output_tokens", output_tokens)
        object.__setattr__(self, "estimated_cost_usd", cost)
        object.__setattr__(self, "finish_reason", finish_reason)


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    finish_reason: str | None
    prompt_hash: str
    response_hash: str

    @property
    def total_tokens(self):
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def to_dict(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "finish_reason": self.finish_reason,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
        }


class LLMTransport(ABC):
    """Provider boundary. It receives text prompts and returns one raw JSON response."""

    @abstractmethod
    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        """Return an LLMCallResult."""


class OpenAICompatibleChatTransport(LLMTransport):
    """Minimal stdlib transport for OpenAI-compatible chat/completions endpoints."""

    def __init__(
        self,
        *,
        base_url,
        model,
        api_key=None,
        provider="openai-compatible",
        extra_headers=None,
        request_json_object=True,
        input_cost_per_million=None,
        output_cost_per_million=None,
    ):
        base_url = _require_text(base_url, "LLM base_url").rstrip("/")
        model = _require_text(model, "LLM model")
        provider = _require_text(provider, "LLM provider")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("LLM base_url must start with http:// or https://")
        if api_key is not None:
            api_key = _require_text(api_key, "LLM api_key")
        if extra_headers is None:
            extra_headers = {}
        if not isinstance(extra_headers, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in extra_headers.items()
        ):
            raise ValueError("LLM extra_headers must be a string mapping")
        if type(request_json_object) is not bool:
            raise ValueError("request_json_object must be boolean")
        self.base_url = base_url
        self.model = model
        self.provider = provider
        self.api_key = api_key
        self.extra_headers = dict(extra_headers)
        self.request_json_object = request_json_object
        self.input_cost_per_million = _optional_non_negative_number(
            input_cost_per_million,
            "input_cost_per_million",
        )
        self.output_cost_per_million = _optional_non_negative_number(
            output_cost_per_million,
            "output_cost_per_million",
        )

    @property
    def endpoint(self):
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    def _estimated_cost(self, input_tokens, output_tokens):
        if (
            input_tokens is None
            or output_tokens is None
            or self.input_cost_per_million is None
            or self.output_cost_per_million is None
        ):
            return None
        return (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        system_prompt = _require_text(system_prompt, "LLM system_prompt")
        user_prompt = _require_text(user_prompt, "LLM user_prompt")
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
                raw = response.read(MAX_LLM_RESPONSE_CHARS * 4)
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
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
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
            estimated_cost_usd=self._estimated_cost(
                input_tokens,
                output_tokens,
            ),
            finish_reason=finish_reason,
        )


PLANNER_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "proposals", "plan_summary"],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["proposals_available", "cannot_progress"],
        },
        "proposals": {
            "type": "array",
            "maxItems": MAX_PROPOSALS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "tool",
                    "tool_version",
                    "arguments",
                    "expected_observation",
                    "rationale_summary",
                ],
                "properties": {
                    "tool": {"type": "string"},
                    "tool_version": {"type": "string"},
                    "arguments": {"type": "object"},
                    "expected_observation": {"type": "string"},
                    "rationale_summary": {"type": "string"},
                },
            },
        },
        "plan_summary": {"type": ["string", "null"]},
    },
}


SYSTEM_PROMPT = """You are the proposal-only Planner for ANIMA.
Return exactly one JSON object and no Markdown.
You may only propose tools listed in planner_request.tools. You never execute tools.
Do not claim authoritative safety, risk, effort, confidence, success, goal completion,
or internal-state values; ANIMA computes those outside the model.
When information is insufficient, prefer an information-gathering tool proposal.
Each proposal is one possible next action, not a multi-step hidden plan.
Do not provide chain-of-thought. Keep plan_summary and rationale_summary brief and
outcome-focused. The response object must contain exactly status, proposals,
plan_summary. Every proposal must contain exactly tool, tool_version, arguments,
expected_observation, rationale_summary.
"""


def build_llm_planner_prompts(request):
    if not isinstance(request, PlannerRequest):
        raise TypeError("build_llm_planner_prompts() requires a PlannerRequest")
    payload = {
        "response_contract": PLANNER_RESPONSE_SCHEMA,
        "planner_request": request.to_dict(),
    }
    return SYSTEM_PROMPT.strip(), _canonical_json(payload)


def parse_llm_planner_decision(text):
    if not isinstance(text, str) or not text.strip():
        raise LLMPlannerError("LLM planner response must be non-empty JSON")
    text = text.strip()
    if len(text) > MAX_LLM_RESPONSE_CHARS:
        raise LLMPlannerError(
            f"LLM planner response exceeds {MAX_LLM_RESPONSE_CHARS} characters"
        )
    if text.startswith("```") or text.endswith("```"):
        raise LLMPlannerError("LLM planner response must not use Markdown fences")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMPlannerError("LLM planner response is not valid JSON") from error

    _require_exact_fields(
        record,
        {"status", "proposals", "plan_summary"},
        "LLM PlannerDecision",
    )
    proposals = record["proposals"]
    if not isinstance(proposals, list):
        raise LLMPlannerError("LLM PlannerDecision proposals must be an array")
    if len(proposals) > MAX_PROPOSALS:
        raise LLMPlannerError(
            f"LLM PlannerDecision exceeds max proposals {MAX_PROPOSALS}"
        )

    drafts = []
    expected = {
        "tool",
        "tool_version",
        "arguments",
        "expected_observation",
        "rationale_summary",
    }
    for index, proposal in enumerate(proposals):
        _require_exact_fields(
            proposal,
            expected,
            f"LLM proposal[{index}]",
        )
        if not isinstance(proposal["arguments"], dict):
            raise LLMPlannerError(
                f"LLM proposal[{index}] arguments must be a JSON object"
            )
        drafts.append(
            ProposalDraft(
                tool=proposal["tool"],
                tool_version=proposal["tool_version"],
                arguments=proposal["arguments"],
                expected_observation=proposal["expected_observation"],
                rationale_summary=proposal["rationale_summary"],
            )
        )

    try:
        return PlannerDecision(
            status=record["status"],
            proposals=tuple(drafts),
            plan_summary=record["plan_summary"],
        )
    except (TypeError, ValueError) as error:
        raise LLMPlannerError(f"Invalid LLM PlannerDecision: {error}") from error


class LLMPlanner(PlannerAdapter):
    """Structured LLM proposal adapter with no execution or writable-state authority."""

    def __init__(
        self,
        transport,
        *,
        name="llm",
        version="1",
        timeout_seconds=DEFAULT_LLM_TIMEOUT_SECONDS,
    ):
        if not isinstance(transport, LLMTransport):
            raise TypeError("LLMPlanner transport must implement LLMTransport")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("LLMPlanner timeout_seconds must be positive")
        super().__init__(name=name, version=version)
        self.transport = transport
        self.timeout_seconds = float(timeout_seconds)
        self._call_history = []

    @property
    def call_history(self):
        return tuple(self._call_history)

    @property
    def last_call(self):
        return self._call_history[-1] if self._call_history else None

    def _decide(self, request):
        system_prompt, user_prompt = build_llm_planner_prompts(request)
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
        return decision


__all__ = [
    "DEFAULT_LLM_TIMEOUT_SECONDS",
    "LLMCallRecord",
    "LLMCallResult",
    "LLMPlanner",
    "LLMPlannerError",
    "LLMTransport",
    "LLMTransportError",
    "MAX_LLM_CALL_HISTORY",
    "MAX_LLM_RESPONSE_CHARS",
    "OpenAICompatibleChatTransport",
    "PLANNER_RESPONSE_SCHEMA",
    "build_llm_planner_prompts",
    "parse_llm_planner_decision",
]
