"""llama.cpp-specific transport for small local Planner models.

This module keeps backend-specific sampling and JSON-schema constraints outside
the generic OpenAI-compatible transport. The Planner contract and compact
PlannerRequest projection remain unchanged.
"""

import json
import time
import urllib.error
import urllib.request

from anima.agent.llm_planner import LLMCallResult, LLMTransportError
from anima.agent.small_llm import SmallModelOpenAICompatibleChatTransport


LLAMA_CPP_DEFAULT_TEMPERATURE = 0.6
LLAMA_CPP_DEFAULT_TOP_K = 20
LLAMA_CPP_DEFAULT_TOP_P = 0.95
LLAMA_CPP_DEFAULT_MIN_P = 0.0


LLAMA_CPP_PLANNER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["proposals_available", "cannot_progress"],
        },
        "proposals": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "tool_version": {"type": "string"},
                    "arguments": {"type": "object"},
                    "expected_observation": {"type": "string"},
                    "rationale_summary": {"type": "string"},
                },
                "required": [
                    "tool",
                    "tool_version",
                    "arguments",
                    "expected_observation",
                    "rationale_summary",
                ],
                "additionalProperties": False,
            },
        },
        # The canonical parser also accepts null. The constrained small-model
        # path intentionally narrows this to a short string for simpler grammar.
        "plan_summary": {"type": "string"},
    },
    "required": ["status", "proposals", "plan_summary"],
    "additionalProperties": False,
}


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _probability(value, label):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{label} must be within 0..1")
    return float(value)


class LlamaCppSmallModelTransport(SmallModelOpenAICompatibleChatTransport):
    """Small-model transport tuned for llama-server chat/completions.

    llama.cpp-specific request fields stay here rather than leaking into the
    generic OpenAI-compatible transport. Reasoning mode is a server concern and
    should be disabled when starting llama-server for the Stage 4.12 baseline.
    """

    def __init__(
        self,
        *,
        temperature=LLAMA_CPP_DEFAULT_TEMPERATURE,
        top_k=LLAMA_CPP_DEFAULT_TOP_K,
        top_p=LLAMA_CPP_DEFAULT_TOP_P,
        min_p=LLAMA_CPP_DEFAULT_MIN_P,
        constrain_json=True,
        **kwargs,
    ):
        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or float(temperature) < 0
        ):
            raise ValueError("temperature must be non-negative")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 0:
            raise ValueError("top_k must be a non-negative integer")
        top_p = _probability(top_p, "top_p")
        min_p = _probability(min_p, "min_p")
        if type(constrain_json) is not bool:
            raise ValueError("constrain_json must be boolean")

        # Parent field request_json_object acts as the existing on/off switch for
        # structured response_format. Here it means llama.cpp JSON Schema mode.
        super().__init__(request_json_object=constrain_json, **kwargs)
        self.temperature = float(temperature)
        self.top_k = top_k
        self.top_p = top_p
        self.min_p = min_p

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
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "min_p": self.min_p,
            "max_tokens": self.max_output_tokens,
        }
        if self.request_json_object:
            payload["response_format"] = {
                "type": "json_schema",
                "schema": LLAMA_CPP_PLANNER_JSON_SCHEMA,
            }

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
                "llama.cpp returned an unsupported chat/completions response"
            ) from error
        if not isinstance(text, str) or not text.strip():
            raise LLMTransportError("llama.cpp returned empty message content")

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
    "LLAMA_CPP_DEFAULT_MIN_P",
    "LLAMA_CPP_DEFAULT_TEMPERATURE",
    "LLAMA_CPP_DEFAULT_TOP_K",
    "LLAMA_CPP_DEFAULT_TOP_P",
    "LLAMA_CPP_PLANNER_JSON_SCHEMA",
    "LlamaCppSmallModelTransport",
]
