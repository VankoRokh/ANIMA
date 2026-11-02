"""Shared text-generation transport primitives for replaceable cognitive roles.

This module owns provider/transport mechanics only. It knows nothing about FAST,
DEEP, Tasks, Goals, Memory, routing, or proposal authority. Role-specific modules
render prompts and adapt the returned LLMCallResult to their own stable contracts.
"""

from dataclasses import dataclass
import json
import re
import time
from typing import Protocol, runtime_checkable
import urllib.error
import urllib.request


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


class LLMTransportError(RuntimeError):
    """A text-generation transport failed before a usable completion."""


class LLMModelOutputError(LLMTransportError):
    """The provider returned output that cannot be exposed as a final answer."""


@dataclass(frozen=True)
class LLMCallResult:
    """Provider-neutral observable metadata for one successful model call."""

    provider: str
    model: str
    text: str
    thinking: bool
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    reasoning_chars: int = 0
    raw_output_chars: int = 0

    def to_dict(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "thinking": self.thinking,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "finish_reason": self.finish_reason,
            "reasoning_chars": self.reasoning_chars,
            "raw_output_chars": self.raw_output_chars,
        }


@runtime_checkable
class TextTransport(Protocol):
    """Provider-neutral text-generation boundary used by cognitive adapters."""

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        ...


def probability(value, label):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{label} must be within 0..1")
    return float(value)


def final_answer(
    text,
    *,
    separate_reasoning=None,
    error_cls=LLMModelOutputError,
    role_label="LLM",
):
    """Strip hidden reasoning and return only a usable final answer."""
    if not isinstance(error_cls, type) or not issubclass(error_cls, Exception):
        raise TypeError("error_cls must be an exception type")
    if not isinstance(role_label, str) or not role_label.strip():
        raise ValueError("role_label must be non-empty")
    role_label = role_label.strip()

    if not isinstance(text, str):
        raise error_cls(f"{role_label} model returned non-text content")

    raw = text.strip()
    if separate_reasoning is not None and not isinstance(separate_reasoning, str):
        separate_reasoning = str(separate_reasoning)

    reasoning_chars = len(separate_reasoning or "")
    lowered = raw.lower()
    if "<think" in lowered and "</think>" not in lowered:
        raise error_cls(
            f"{role_label} model reasoning reached the output limit before a final answer"
        )

    matches = list(_THINK_BLOCK.finditer(raw))
    if matches:
        reasoning_chars += sum(len(match.group(0)) for match in matches)
        raw = _THINK_BLOCK.sub("", raw).strip()

    if not raw:
        raise error_cls(f"{role_label} model returned no final answer")
    return raw, reasoning_chars


class LlamaCppTransport:
    """Stateless text transport using llama-server native endpoints.

    Subclasses may override the error classes and role label for compatibility,
    while the HTTP/template/completion mechanics remain shared.
    """

    transport_error_cls = LLMTransportError
    model_output_error_cls = LLMModelOutputError
    role_label = "LLM"

    def __init__(
        self,
        *,
        base_url="http://127.0.0.1:8080",
        model="local-model",
        thinking=False,
        max_output_tokens=512,
        temperature=0.6,
        top_k=20,
        top_p=0.95,
        min_p=0.0,
        api_key=None,
    ):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("llama.cpp base_url must be non-empty")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("llama.cpp model label must be non-empty")
        if type(thinking) is not bool:
            raise ValueError("llama.cpp thinking must be boolean")
        if (
            not isinstance(max_output_tokens, int)
            or isinstance(max_output_tokens, bool)
            or max_output_tokens <= 0
        ):
            raise ValueError("llama.cpp max_output_tokens must be positive")
        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or float(temperature) < 0
        ):
            raise ValueError("llama.cpp temperature must be non-negative")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 0:
            raise ValueError("llama.cpp top_k must be a non-negative integer")

        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.thinking = thinking
        self.max_output_tokens = max_output_tokens
        self.temperature = float(temperature)
        self.top_k = top_k
        self.top_p = probability(top_p, "top_p")
        self.min_p = probability(min_p, "min_p")
        self.api_key = api_key

    @property
    def server_root(self):
        base = self.base_url
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
        }
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8"),
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
            raise self.transport_error_cls(message) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise self.transport_error_cls(
                f"llama.cpp {self.role_label} transport failed: {error}"
            ) from error

        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise self.transport_error_cls("llama.cpp returned invalid JSON") from error
        if not isinstance(document, dict):
            raise self.transport_error_cls("llama.cpp returned a non-object response")
        if "error" in document:
            raise self.transport_error_cls(
                "llama.cpp returned an error: "
                + json.dumps(document["error"], ensure_ascii=False)
            )
        return document

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError(f"{self.role_label} system_prompt must be non-empty")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError(f"{self.role_label} user_prompt must be non-empty")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        started = time.perf_counter()
        template = self._post_json(
            self.apply_template_endpoint,
            {
                "messages": messages,
                "add_generation_prompt": True,
                "chat_template_kwargs": {"enable_thinking": self.thinking},
            },
            timeout_seconds=timeout_seconds,
        )
        prompt = template.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise self.transport_error_cls(
                "llama.cpp /apply-template returned no prompt"
            )

        document = self._post_json(
            self.completion_endpoint,
            {
                "prompt": prompt,
                "n_predict": self.max_output_tokens,
                "temperature": self.temperature,
                "top_k": self.top_k,
                "top_p": self.top_p,
                "min_p": self.min_p,
                "stream": False,
            },
            timeout_seconds=timeout_seconds,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        raw_text = document.get("content")
        separate_reasoning = document.get("reasoning_content")
        final_text, reasoning_chars = final_answer(
            raw_text,
            separate_reasoning=separate_reasoning,
            error_cls=self.model_output_error_cls,
            role_label=self.role_label,
        )

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

        raw_output_chars = len(raw_text) if isinstance(raw_text, str) else 0
        if isinstance(separate_reasoning, str):
            raw_output_chars += len(separate_reasoning)

        return LLMCallResult(
            provider="llama.cpp",
            model=self.model,
            text=final_text,
            thinking=self.thinking,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
            reasoning_chars=reasoning_chars,
            raw_output_chars=raw_output_chars,
        )


__all__ = [
    "LLMCallResult",
    "LLMModelOutputError",
    "LLMTransportError",
    "LlamaCppTransport",
    "TextTransport",
    "final_answer",
    "probability",
]
