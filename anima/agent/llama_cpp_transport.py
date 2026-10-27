"""llama.cpp-specific transport for small local Planner models.

This module keeps backend-specific sampling and JSON-schema constraints outside
the generic OpenAI-compatible transport. The Planner contract and compact
PlannerRequest projection remain unchanged.

For constrained Planner output we intentionally use llama-server's native
/apply-template -> /completion path. The current Stage 4.12 baseline verified
that /completion + json_schema enforces the schema, while the OpenAI-compatible
chat endpoint may accept response_format without enforcing it for this build.
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
    """Small-model transport tuned for llama-server native completion APIs.

    The transport first asks /apply-template to render the system/user messages
    with the model's own chat template, explicitly disabling thinking. It then
    sends that rendered prompt to /completion, where llama.cpp's json_schema
    field constrains generated tokens before ANIMA performs its own strict parse.
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

        # Parent field request_json_object remains the existing structured-output
        # switch. In this backend it controls native /completion json_schema.
        super().__init__(request_json_object=constrain_json, **kwargs)
        self.temperature = float(temperature)
        self.top_k = top_k
        self.top_p = top_p
        self.min_p = min_p

    @property
    def server_root(self):
        """Return llama-server root even when configured with an OpenAI /v1 URL."""
        base = self.base_url.rstrip("/")
        for suffix in (
            "/v1/chat/completions",
            "/chat/completions",
            "/v1/completions",
            "/completions",
            "/completion",
            "/v1",
        ):
            if base.endswith(suffix):
                return base[: -len(suffix)]
        return base

    @property
    def apply_template_endpoint(self):
        return self.server_root + "/apply-template"

    @property
    def completion_endpoint(self):
        return self.server_root + "/completion"

    def _post_json(self, endpoint, payload, *, timeout_seconds):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self.extra_headers,
        }
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            endpoint,
            data=_canonical_json(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
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
            message = f"llama.cpp HTTP {error.code}"
            if detail.strip():
                message += ": " + detail.strip()
            raise LLMTransportError(message) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LLMTransportError(f"llama.cpp transport failed: {error}") from error

        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LLMTransportError("llama.cpp returned invalid JSON") from error
        if not isinstance(document, dict):
            raise LLMTransportError("llama.cpp returned a non-object JSON response")
        if "error" in document:
            raise LLMTransportError(
                "llama.cpp returned an error: " + _canonical_json(document["error"])
            )
        return document

    def complete_structured(
        self,
        *,
        system_prompt,
        user_prompt,
        timeout_seconds,
        response_schema,
    ):
        if not isinstance(response_schema, dict) or not response_schema:
            raise ValueError("response_schema must be a non-empty JSON Schema object")
        return self._complete_native(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout_seconds,
            response_schema=(response_schema if self.request_json_object else None),
        )

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        response_schema = (
            LLAMA_CPP_PLANNER_JSON_SCHEMA if self.request_json_object else None
        )
        return self._complete_native(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout_seconds,
            response_schema=response_schema,
        )

    def _complete_native(
        self,
        *,
        system_prompt,
        user_prompt,
        timeout_seconds,
        response_schema,
    ):
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
        if response_schema is not None and not isinstance(response_schema, dict):
            raise ValueError("response_schema must be a JSON Schema object or null")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        started = time.perf_counter()

        template_document = self._post_json(
            self.apply_template_endpoint,
            {
                "messages": messages,
                "add_generation_prompt": True,
                "enable_thinking": False,
            },
            timeout_seconds=timeout_seconds,
        )
        rendered_prompt = template_document.get("prompt")
        if not isinstance(rendered_prompt, str) or not rendered_prompt:
            raise LLMTransportError("llama.cpp /apply-template returned no prompt")

        completion_payload = {
            "prompt": rendered_prompt,
            "n_predict": self.max_output_tokens,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "min_p": self.min_p,
            "stream": False,
        }
        if response_schema is not None:
            completion_payload["json_schema"] = response_schema

        document = self._post_json(
            self.completion_endpoint,
            completion_payload,
            timeout_seconds=timeout_seconds,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        text = document.get("content")
        if not isinstance(text, str) or not text.strip():
            raise LLMTransportError("llama.cpp /completion returned empty content")

        input_tokens = document.get("tokens_evaluated")
        output_tokens = document.get("tokens_predicted")
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool):
            input_tokens = None
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            output_tokens = None

        finish_reason = document.get("stop_type")
        if finish_reason is None and document.get("stop") is True:
            finish_reason = "stop"
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
