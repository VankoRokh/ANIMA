import pytest

from anima.cognition.fast import FastRequest, FastResult
from anima.cognition.fast_llm import (
    FAST_SYSTEM_PROMPT,
    FastLLMBackend,
    FastLLMCallResult,
    FastLLMTransportError,
    LlamaCppFastTransport,
    _final_answer,
    render_fast_prompts,
)


class StubTransport:
    def __init__(self, text="Ответ FAST"):
        self.text = text
        self.calls = []

    def complete(self, *, system_prompt, user_prompt, timeout_seconds):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        return FastLLMCallResult(
            provider="stub",
            model="stub-model",
            text=self.text,
            thinking=False,
            latency_ms=1.5,
            input_tokens=10,
            output_tokens=4,
            finish_reason="stop",
            raw_output_chars=len(self.text),
        )


class RecordingLlamaCppTransport(LlamaCppFastTransport):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.requests = []

    def _post_json(self, endpoint, payload, *, timeout_seconds):
        self.requests.append((endpoint, payload, timeout_seconds))
        if endpoint.endswith("/apply-template"):
            return {"prompt": "rendered prompt"}
        return {
            "content": "Финальный ответ",
            "tokens_evaluated": 31,
            "tokens_predicted": 7,
            "stop": True,
        }


def fast_request(*, memories=(), knowledge=(), text="Что ты помнишь?"):
    return FastRequest(
        input_event_id="ev_11111111-1111-4111-8111-111111111111",
        input_text=text,
        context_bundle={
            "query": text,
            "consumer": "FAST",
            "budget": {"max_items": 6, "max_chars": 1200},
            "knowledge": [
                {
                    "record": {
                        "id": f"kn_{index:032x}",
                        "statement": statement,
                    }
                }
                for index, statement in enumerate(knowledge, 1)
            ],
            "memories": [
                {
                    "record": {
                        "id": f"mem_{index:032x}",
                        "content": content,
                    }
                }
                for index, content in enumerate(memories, 1)
            ],
            "events": [],
            "truncated": False,
            "selection_stats": {"items_used": 0, "chars_used": 0},
        },
    )


def test_fast_prompt_renderer_exposes_content_not_internal_ids():
    request = fast_request(
        memories=("Пользователь предпочитает кофе эспрессо.",),
        knowledge=("ANIMA использует SQLite для Cognitive Memory.",),
        text="Какой кофе я предпочитаю?",
    )

    system_prompt, user_prompt = render_fast_prompts(request)

    assert system_prompt == FAST_SYSTEM_PROMPT
    assert "Пользователь предпочитает кофе эспрессо." in user_prompt
    assert "ANIMA использует SQLite для Cognitive Memory." in user_prompt
    assert "Какой кофе я предпочитаю?" in user_prompt
    assert "mem_" not in user_prompt
    assert "kn_" not in user_prompt


def test_fast_prompt_renderer_marks_empty_memory_context():
    _, user_prompt = render_fast_prompts(
        fast_request(text="Как зовут мою собаку?")
    )

    assert "релевантная память не выбрана" in user_prompt


def test_fast_llm_backend_adapts_transport_to_fast_result():
    transport = StubTransport("Ты предпочитаешь эспрессо.")
    backend = FastLLMBackend(transport, timeout_seconds=12.0)
    request = fast_request(
        memories=("Пользователь предпочитает кофе эспрессо.",),
        text="Какой кофе я предпочитаю?",
    )

    result = backend.complete(request)

    assert result == FastResult(response_text="Ты предпочитаешь эспрессо.")
    assert len(transport.calls) == 1
    assert transport.calls[0]["timeout_seconds"] == 12.0
    assert backend.call_history[0].model == "stub-model"


def test_thinking_block_is_removed_from_fast_answer():
    final, reasoning_chars = _final_answer(
        "<think>Скрытое рассуждение модели.</think>\nТы предпочитаешь эспрессо."
    )

    assert final == "Ты предпочитаешь эспрессо."
    assert reasoning_chars > 0


def test_unfinished_thinking_is_not_exposed_as_fast_answer():
    with pytest.raises(FastLLMTransportError, match="output limit"):
        _final_answer("<think>Модель ещё рассуждает")


def test_llama_cpp_transport_passes_thinking_flag_without_json_schema():
    transport = RecordingLlamaCppTransport(
        base_url="http://127.0.0.1:8080/v1",
        model="Qwen3-0.6B-Q8_0",
        thinking=True,
        max_output_tokens=512,
    )

    call = transport.complete(
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=30.0,
    )

    assert call.text == "Финальный ответ"
    assert call.thinking is True
    assert call.input_tokens == 31
    assert call.output_tokens == 7
    assert len(transport.requests) == 2

    apply_endpoint, apply_payload, _ = transport.requests[0]
    completion_endpoint, completion_payload, _ = transport.requests[1]
    assert apply_endpoint.endswith("/apply-template")
    assert apply_payload["enable_thinking"] is True
    assert completion_endpoint.endswith("/completion")
    assert completion_payload["n_predict"] == 512
    assert "json_schema" not in completion_payload


def test_llama_cpp_transport_can_disable_thinking():
    transport = RecordingLlamaCppTransport(thinking=False)

    transport.complete(
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=30.0,
    )

    assert transport.requests[0][1]["enable_thinking"] is False
